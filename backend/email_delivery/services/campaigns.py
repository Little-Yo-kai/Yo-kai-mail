import csv
import hashlib
import io
import logging
from datetime import timezone as datetime_timezone

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from campaigns.models import Campaign, CampaignStatus
from campaigns.services import (
    CampaignTransitionError,
    CampaignWorkflowError,
    render_campaign_email,
    transition_campaign,
)

from .resend import ResendDeliveryError, ResendEmailService, ResendNotConfiguredError
from ..models import (
    AudienceSnapshot,
    AudienceSnapshotRecipient,
    CampaignSendJob,
    CampaignSendJobStatus,
    ConsentStatus,
    Contact,
    ContactList,
    ContactListMembership,
    ContactStatus,
    DeliveryEvent,
    DeliveryRecord,
    DeliveryRecordStatus,
    normalize_email,
)

logger = logging.getLogger(__name__)


class ContactImportError(ValueError):
    pass


class CampaignDeliveryError(ValueError):
    pass


class CampaignQueueError(RuntimeError):
    pass


def _consent_timestamp(value):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, datetime_timezone.utc)
    return parsed


def import_contacts_csv(*, uploaded_file, owner, contact_list=None):
    text_stream = None
    try:
        text_stream = io.TextIOWrapper(
            uploaded_file,
            encoding="utf-8-sig",
            newline="",
        )
        reader = csv.DictReader(text_stream)
        header_lookup = {
            (header or "").strip().casefold(): header
            for header in (reader.fieldnames or [])
        }
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ContactImportError("The uploaded file is not a valid UTF-8 CSV.") from exc

    if "email" not in header_lookup:
        raise ContactImportError("The CSV must include an email column.")

    counts = {"accepted": 0, "duplicate": 0, "invalid": 0, "skipped": 0}
    row_errors = []

    def value_for(row, field):
        return (row.get(header_lookup.get(field, "")) or "").strip()

    try:
        with transaction.atomic():
            for row_number, row in enumerate(reader, start=2):
                if not any(
                    isinstance(value, str) and value.strip()
                    for value in row.values()
                ):
                    counts["skipped"] += 1
                    continue

                if row.get(None):
                    counts["invalid"] += 1
                    if len(row_errors) < 100:
                        row_errors.append(
                            {"row": row_number, "reason": "Too many columns."}
                        )
                    continue

                email = value_for(row, "email")
                try:
                    validate_email(email)
                except ValidationError:
                    counts["invalid"] += 1
                    if len(row_errors) < 100:
                        row_errors.append(
                            {"row": row_number, "reason": "Invalid email address."}
                        )
                    continue

                consent_value = value_for(row, "consent_status").casefold()
                if consent_value not in {
                    "",
                    ConsentStatus.UNKNOWN,
                    ConsentStatus.GRANTED,
                    ConsentStatus.WITHDRAWN,
                }:
                    counts["invalid"] += 1
                    if len(row_errors) < 100:
                        row_errors.append(
                            {"row": row_number, "reason": "Invalid consent_status."}
                        )
                    continue

                consented_at = _consent_timestamp(value_for(row, "consented_at"))
                if consent_value == ConsentStatus.GRANTED and consented_at is None:
                    counts["invalid"] += 1
                    if len(row_errors) < 100:
                        row_errors.append(
                            {
                                "row": row_number,
                                "reason": "consented_at is required for granted consent.",
                            }
                        )
                    continue

                normalized = normalize_email(email)
                existing = Contact.objects.filter(
                    owner=owner,
                    normalized_email=normalized,
                ).first()
                if existing:
                    counts["duplicate"] += 1
                    contact = existing
                    if consent_value == ConsentStatus.WITHDRAWN:
                        contact.status = ContactStatus.UNSUBSCRIBED
                        contact.consent_status = ConsentStatus.WITHDRAWN
                        contact.save(
                            update_fields=["status", "consent_status", "updated_at"]
                        )
                else:
                    status_value = ContactStatus.PENDING_CONSENT
                    if consent_value == ConsentStatus.GRANTED:
                        status_value = ContactStatus.ACTIVE
                    elif consent_value == ConsentStatus.WITHDRAWN:
                        status_value = ContactStatus.UNSUBSCRIBED

                    try:
                        with transaction.atomic():
                            contact = Contact.objects.create(
                                owner=owner,
                                email=email,
                                first_name=value_for(row, "first_name"),
                                last_name=value_for(row, "last_name"),
                                display_name=value_for(row, "display_name"),
                                status=status_value,
                                consent_status=consent_value or ConsentStatus.UNKNOWN,
                                consent_source=value_for(row, "consent_source"),
                                consented_at=consented_at,
                                source=value_for(row, "source") or "csv_import",
                            )
                    except IntegrityError:
                        counts["duplicate"] += 1
                        contact = Contact.objects.get(
                            owner=owner,
                            normalized_email=normalized,
                        )
                    else:
                        counts["accepted"] += 1

                if contact_list:
                    ContactListMembership.objects.get_or_create(
                        contact_list=contact_list,
                        contact=contact,
                        defaults={"source": "csv_import"},
                    )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ContactImportError("The uploaded file could not be parsed as CSV.") from exc
    finally:
        if text_stream is not None:
            try:
                text_stream.detach()
            except (AttributeError, ValueError):
                pass

    counts["row_errors"] = row_errors
    return counts


@transaction.atomic
def resolve_campaign_audience(*, campaign_id, owner, list_ids, contact_ids):
    campaign = Campaign.objects.select_for_update().get(
        id=campaign_id,
        owner=owner,
    )
    if campaign.status not in {
        CampaignStatus.GENERATED,
        CampaignStatus.REVIEWED,
        CampaignStatus.TEST_SENT,
        CampaignStatus.READY,
    }:
        raise CampaignDeliveryError(
            "The audience cannot be changed in the campaign's current state."
        )
    if CampaignSendJob.objects.exclude(
        status=CampaignSendJobStatus.CANCELED
    ).filter(campaign=campaign).exists():
        raise CampaignDeliveryError(
            "The audience is locked after a campaign delivery job is created."
        )

    owned_lists = list(
        ContactList.objects.filter(owner=owner, id__in=list_ids)
    )
    if len(owned_lists) != len(set(list_ids)):
        raise CampaignDeliveryError("One or more contact lists were not found.")

    owned_contacts = list(
        Contact.objects.filter(owner=owner, id__in=contact_ids)
    )
    if len(owned_contacts) != len(set(contact_ids)):
        raise CampaignDeliveryError("One or more contacts were not found.")

    selection = Q()
    if list_ids:
        selection |= Q(list_memberships__contact_list_id__in=list_ids)
    if contact_ids:
        selection |= Q(id__in=contact_ids)

    candidates = list(
        Contact.objects.filter(owner=owner)
        .filter(selection)
        .distinct()
        .order_by("normalized_email")
    )

    unique_by_email = {}
    for contact in candidates:
        unique_by_email.setdefault(contact.normalized_email, contact)
    unique_candidates = list(unique_by_email.values())
    eligible = [
        contact
        for contact in unique_candidates
        if contact.status == ContactStatus.ACTIVE
        and contact.consent_status == ConsentStatus.GRANTED
        and contact.consented_at is not None
    ]

    snapshot = AudienceSnapshot.objects.create(
        owner=owner,
        campaign=campaign,
        criteria={
            "list_ids": [str(item) for item in list_ids],
            "contact_ids": [str(item) for item in contact_ids],
        },
        recipient_count=len(eligible),
    )
    AudienceSnapshotRecipient.objects.bulk_create(
        [
            AudienceSnapshotRecipient(
                snapshot=snapshot,
                contact=contact,
                contact_id_snapshot=contact.id,
                email=contact.email,
                normalized_email=contact.normalized_email,
                display_name=contact.display_name,
            )
            for contact in eligible
        ]
    )

    excluded_status = sum(
        1
        for contact in unique_candidates
        if contact.status != ContactStatus.ACTIVE
    )
    excluded_consent = sum(
        1
        for contact in unique_candidates
        if contact.consent_status != ConsentStatus.GRANTED
        or contact.consented_at is None
    )
    campaign.audience_selection = {
        "list_ids": [str(item) for item in list_ids],
        "contact_ids": [str(item) for item in contact_ids],
    }
    campaign.audience_snapshot_id = snapshot.id
    campaign.save(
        update_fields=[
            "audience_selection",
            "audience_snapshot_id",
            "updated_at",
        ]
    )

    return {
        "snapshot_id": str(snapshot.id),
        "recipient_count": len(eligible),
        "selected_contact_count": len(candidates),
        "duplicate_count": len(candidates) - len(unique_candidates),
        "excluded_status_count": excluded_status,
        "excluded_consent_count": excluded_consent,
    }


@transaction.atomic
def create_campaign_send_job(*, campaign_id, owner, scheduled_for=None):
    campaign = (
        Campaign.objects.select_for_update()
        .select_related("active_design")
        .get(id=campaign_id, owner=owner)
    )
    if campaign.status != CampaignStatus.READY:
        raise CampaignDeliveryError("Only a ready campaign can be sent.")
    if not campaign.active_design_id:
        raise CampaignDeliveryError("The campaign has no active email design.")
    if not campaign.audience_snapshot_id:
        raise CampaignDeliveryError("Resolve a campaign audience before sending.")
    if CampaignSendJob.objects.exclude(
        status=CampaignSendJobStatus.CANCELED
    ).filter(campaign=campaign).exists():
        raise CampaignDeliveryError("A send job already exists for this campaign.")

    try:
        snapshot = AudienceSnapshot.objects.get(
            id=campaign.audience_snapshot_id,
            campaign=campaign,
            owner=owner,
        )
    except AudienceSnapshot.DoesNotExist as exc:
        raise CampaignDeliveryError(
            "The campaign audience snapshot is invalid. Resolve it again."
        ) from exc

    recipients = list(snapshot.recipients.select_related("contact"))
    if not recipients:
        raise CampaignDeliveryError(
            "The resolved audience has no contacts with active recorded consent."
        )

    try:
        render_campaign_email(campaign)
    except CampaignWorkflowError:
        raise
    except Exception as exc:
        raise CampaignWorkflowError(
            "The campaign email could not be rendered for delivery."
        ) from exc

    is_scheduled = scheduled_for is not None
    next_status = (
        CampaignStatus.SCHEDULED if is_scheduled else CampaignStatus.SENDING
    )
    try:
        transition_campaign(campaign, next_status=next_status)
    except CampaignTransitionError as exc:
        raise CampaignDeliveryError(str(exc)) from exc

    campaign.send_mode = "scheduled" if is_scheduled else "send_now"
    campaign.scheduled_for = scheduled_for
    campaign.save(update_fields=["send_mode", "scheduled_for", "updated_at"])

    job = CampaignSendJob.objects.create(
        campaign=campaign,
        owner=owner,
        audience_snapshot=snapshot,
        status=(
            CampaignSendJobStatus.SCHEDULED
            if is_scheduled
            else CampaignSendJobStatus.QUEUED
        ),
        scheduled_for=scheduled_for,
    )
    DeliveryRecord.objects.bulk_create(
        [
            DeliveryRecord(
                job=job,
                campaign=campaign,
                audience_snapshot=snapshot,
                contact=recipient.contact,
                contact_id_snapshot=recipient.contact_id_snapshot,
                recipient_email=recipient.email,
                normalized_email=recipient.normalized_email,
                idempotency_key=(
                    f"campaign/{campaign.id}/job/{job.id}/recipient/"
                    f"{hashlib.sha256(recipient.normalized_email.encode()).hexdigest()}"
                ),
            )
            for recipient in recipients
        ]
    )
    return job


def dispatch_campaign_send_job(job):
    from email_delivery.tasks import deliver_campaign_send_job

    try:
        options = {"args": [str(job.id)]}
        if job.scheduled_for:
            options["eta"] = job.scheduled_for
        deliver_campaign_send_job.apply_async(**options)
    except Exception as exc:
        logger.exception("Could not queue campaign delivery job %s", job.id)
        fail_campaign_send_job(job.id, "The delivery worker could not be queued.")
        raise CampaignQueueError(
            "The delivery worker is unavailable. The campaign was not sent."
        ) from exc


@transaction.atomic
def cancel_campaign_schedule(*, campaign_id, owner):
    campaign = Campaign.objects.select_for_update().get(
        id=campaign_id,
        owner=owner,
    )
    try:
        job = CampaignSendJob.objects.select_for_update().get(
            campaign=campaign,
            status=CampaignSendJobStatus.SCHEDULED,
        )
    except CampaignSendJob.DoesNotExist as exc:
        raise CampaignDeliveryError(
            "The campaign has no scheduled delivery to cancel."
        ) from exc
    if (
        job.status != CampaignSendJobStatus.SCHEDULED
        or campaign.status != CampaignStatus.SCHEDULED
    ):
        raise CampaignDeliveryError(
            "The campaign delivery has already started or is not scheduled."
        )

    now = timezone.now()
    job.status = CampaignSendJobStatus.CANCELED
    job.completed_at = now
    job.error_summary = "Schedule canceled by the campaign owner."
    job.save(
        update_fields=["status", "completed_at", "error_summary", "updated_at"]
    )
    job.deliveries.filter(status=DeliveryRecordStatus.QUEUED).update(
        status=DeliveryRecordStatus.CANCELED,
        updated_at=now,
    )
    transition_campaign(campaign, next_status=CampaignStatus.READY)
    campaign.send_mode = "none"
    campaign.scheduled_for = None
    campaign.save(update_fields=["send_mode", "scheduled_for", "updated_at"])
    return job


@transaction.atomic
def fail_campaign_send_job(job_id, reason):
    job = CampaignSendJob.objects.select_for_update().select_related("campaign").get(
        id=job_id
    )
    if job.status in {
        CampaignSendJobStatus.SENT,
        CampaignSendJobStatus.FAILED,
        CampaignSendJobStatus.PARTIAL_FAILED,
        CampaignSendJobStatus.CANCELED,
    }:
        return job
    job.status = CampaignSendJobStatus.FAILED
    job.error_summary = reason
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "error_summary", "completed_at", "updated_at"])
    job.deliveries.filter(status=DeliveryRecordStatus.QUEUED).update(
        status=DeliveryRecordStatus.FAILED,
        failure_reason=reason,
        updated_at=timezone.now(),
    )
    campaign = Campaign.objects.select_for_update().get(id=job.campaign_id)
    if campaign.status in {CampaignStatus.SENDING, CampaignStatus.SCHEDULED}:
        transition_campaign(campaign, next_status=CampaignStatus.FAILED)
    return job


def _mark_contact_unavailable(delivery):
    contact = delivery.contact
    return not (
        contact
        and contact.status == ContactStatus.ACTIVE
        and contact.consent_status == ConsentStatus.GRANTED
        and contact.consented_at is not None
    )


def execute_campaign_send_job(job_id):
    if not settings.RESEND_CAMPAIGN_SEND_ENABLED:
        fail_campaign_send_job(job_id, "Campaign sending is disabled.")
        return CampaignSendJob.objects.get(id=job_id)

    with transaction.atomic():
        job = (
            CampaignSendJob.objects.select_for_update()
            .select_related("campaign__active_design", "audience_snapshot")
            .get(id=job_id)
        )
        if job.status in {
            CampaignSendJobStatus.SENT,
            CampaignSendJobStatus.PARTIAL_FAILED,
            CampaignSendJobStatus.FAILED,
            CampaignSendJobStatus.CANCELED,
        }:
            return job
        if job.scheduled_for and job.scheduled_for > timezone.now():
            return job

        campaign = Campaign.objects.select_for_update().get(id=job.campaign_id)
        expected_status = (
            CampaignStatus.SCHEDULED
            if job.status == CampaignSendJobStatus.SCHEDULED
            else CampaignStatus.SENDING
        )
        if campaign.status != expected_status:
            job.status = CampaignSendJobStatus.CANCELED
            job.error_summary = "Campaign state changed before delivery began."
            job.completed_at = timezone.now()
            job.save(
                update_fields=["status", "error_summary", "completed_at", "updated_at"]
            )
            job.deliveries.filter(status=DeliveryRecordStatus.QUEUED).update(
                status=DeliveryRecordStatus.CANCELED,
                updated_at=timezone.now(),
            )
            return job

        if campaign.status == CampaignStatus.SCHEDULED:
            transition_campaign(campaign, next_status=CampaignStatus.SENDING)
        job.status = CampaignSendJobStatus.SENDING
        job.started_at = job.started_at or timezone.now()
        job.save(update_fields=["status", "started_at", "updated_at"])

    try:
        render_result = render_campaign_email(
            Campaign.objects.select_related("active_design").get(id=job.campaign_id)
        )
    except Exception:
        logger.exception("Campaign rendering failed for job %s", job_id)
        fail_campaign_send_job(job_id, "The campaign email could not be rendered.")
        return CampaignSendJob.objects.get(id=job_id)

    for delivery in job.deliveries.select_related("contact").order_by("created_at"):
        delivery.refresh_from_db(fields=["status", "contact_id"])
        if delivery.status != DeliveryRecordStatus.QUEUED:
            continue
        if _mark_delivery_contact_ineligible(delivery.id):
            continue

        try:
            receipt = ResendEmailService().send_campaign_email(
                to=delivery.normalized_email,
                subject=job.campaign.active_design.email_design["subject"],
                html=render_result["html"],
                idempotency_key=delivery.idempotency_key,
            )
        except (ResendDeliveryError, ResendNotConfiguredError) as exc:
            logger.warning(
                "Campaign delivery failed for %s: %s",
                delivery.id,
                exc,
            )
            DeliveryRecord.objects.filter(id=delivery.id).update(
                status=DeliveryRecordStatus.FAILED,
                failure_reason=str(exc)[:500],
                updated_at=timezone.now(),
            )
            continue
        except Exception:
            logger.exception("Unexpected campaign delivery failure for %s", delivery.id)
            DeliveryRecord.objects.filter(id=delivery.id).update(
                status=DeliveryRecordStatus.FAILED,
                failure_reason="Unexpected delivery error.",
                updated_at=timezone.now(),
            )
            continue

        sent_at = timezone.now()
        with transaction.atomic():
            locked_delivery = DeliveryRecord.objects.select_for_update().get(
                id=delivery.id
            )
            locked_delivery.provider_message_id = receipt["email_id"]
            locked_delivery.status = DeliveryRecordStatus.SENT
            locked_delivery.sent_at = sent_at
            locked_delivery.last_event_type = "email.sent"
            locked_delivery.last_event_at = sent_at
            locked_delivery.save(
                update_fields=[
                    "provider_message_id",
                    "status",
                    "sent_at",
                    "last_event_type",
                    "last_event_at",
                    "updated_at",
                ]
            )
            _apply_unmatched_provider_events(locked_delivery)

    with transaction.atomic():
        job = CampaignSendJob.objects.select_for_update().get(id=job_id)
        campaign = Campaign.objects.select_for_update().get(id=job.campaign_id)
        records = job.deliveries.all()
        sent_count = records.exclude(
            status__in={
                DeliveryRecordStatus.QUEUED,
                DeliveryRecordStatus.FAILED,
                DeliveryRecordStatus.SUPPRESSED,
                DeliveryRecordStatus.CANCELED,
            }
        ).count()
        failed_count = records.filter(status=DeliveryRecordStatus.FAILED).count()
        suppressed_count = records.filter(
            status=DeliveryRecordStatus.SUPPRESSED
        ).count()
        pending_count = records.filter(status=DeliveryRecordStatus.QUEUED).count()

        if pending_count:
            records.filter(status=DeliveryRecordStatus.QUEUED).update(
                status=DeliveryRecordStatus.FAILED,
                failure_reason="Delivery did not complete.",
                updated_at=timezone.now(),
            )
            failed_count += pending_count

        job.completed_at = timezone.now()
        if not sent_count and suppressed_count and not failed_count:
            job.status = CampaignSendJobStatus.FAILED
            job.error_summary = "No recipients remained eligible at send time."
            next_campaign_status = CampaignStatus.FAILED
        elif failed_count and sent_count:
            job.status = CampaignSendJobStatus.PARTIAL_FAILED
            job.error_summary = "One or more recipients could not be sent."
            next_campaign_status = CampaignStatus.FAILED
        elif failed_count:
            job.status = CampaignSendJobStatus.FAILED
            job.error_summary = "No recipient emails were accepted for delivery."
            next_campaign_status = CampaignStatus.FAILED
        else:
            job.status = CampaignSendJobStatus.SENT
            next_campaign_status = CampaignStatus.SENT
        job.save(
            update_fields=["status", "error_summary", "completed_at", "updated_at"]
        )
        if campaign.status == CampaignStatus.SENDING:
            transition_campaign(campaign, next_status=next_campaign_status)
        return job


def _mark_delivery_contact_ineligible(delivery_id):
    with transaction.atomic():
        delivery = DeliveryRecord.objects.select_for_update().select_related("contact").get(
            id=delivery_id
        )
        if not _mark_contact_unavailable(delivery):
            return False
        delivery.status = DeliveryRecordStatus.SUPPRESSED
        delivery.failure_reason = "Recipient was unsubscribed or suppressed before send."
        delivery.last_event_type = "local.suppressed"
        delivery.last_event_at = timezone.now()
        delivery.save(
            update_fields=[
                "status",
                "failure_reason",
                "last_event_type",
                "last_event_at",
                "updated_at",
            ]
        )
        return True


RESEND_EVENT_STATUS = {
    "email.sent": DeliveryRecordStatus.SENT,
    "email.delivery_delayed": DeliveryRecordStatus.DELIVERY_DELAYED,
    "email.delivered": DeliveryRecordStatus.DELIVERED,
    "email.bounced": DeliveryRecordStatus.BOUNCED,
    "email.failed": DeliveryRecordStatus.FAILED,
    "email.suppressed": DeliveryRecordStatus.SUPPRESSED,
    "email.complained": DeliveryRecordStatus.COMPLAINED,
    "email.opened": DeliveryRecordStatus.OPENED,
    "email.clicked": DeliveryRecordStatus.CLICKED,
}


def _apply_delivery_event(delivery, event):
    event.delivery = delivery
    event.save(update_fields=["delivery"])

    if event.occurred_at is not None and (
        delivery.last_event_at is None
        or event.occurred_at >= delivery.last_event_at
    ):
        delivery.status = RESEND_EVENT_STATUS.get(
            event.event_type,
            delivery.status,
        )
        delivery.last_event_type = event.event_type
        delivery.last_event_at = event.occurred_at
        delivery.save(
            update_fields=[
                "status",
                "last_event_type",
                "last_event_at",
                "updated_at",
            ]
        )

    contact_status = {
        "email.bounced": ContactStatus.BOUNCED,
        "email.complained": ContactStatus.COMPLAINED,
        "email.suppressed": ContactStatus.SUPPRESSED,
    }.get(event.event_type)
    if contact_status and delivery.contact_id:
        contact = delivery.contact
        status_priority = {
            ContactStatus.ACTIVE: 0,
            ContactStatus.PENDING_CONSENT: 0,
            ContactStatus.SUPPRESSED: 1,
            ContactStatus.BOUNCED: 2,
            ContactStatus.COMPLAINED: 3,
            ContactStatus.UNSUBSCRIBED: 4,
        }
        if status_priority[contact_status] > status_priority[contact.status]:
            contact.status = contact_status
            contact.consent_status = ConsentStatus.WITHDRAWN
            contact.save(
                update_fields=["status", "consent_status", "updated_at"]
            )


def _apply_unmatched_provider_events(delivery):
    if not delivery.provider_message_id:
        return
    events = DeliveryEvent.objects.filter(
        provider_message_id=delivery.provider_message_id,
        delivery__isnull=True,
    ).order_by("occurred_at", "created_at")
    for event in events:
        _apply_delivery_event(delivery, event)
        delivery.refresh_from_db()


def record_resend_webhook(*, provider_event_id, payload):
    event_type = payload.get("type")
    event_data = payload.get("data")
    if not isinstance(event_type, str):
        raise ValueError("Invalid Resend webhook payload.")
    if event_type not in RESEND_EVENT_STATUS:
        return {"accepted": True, "ignored": True, "duplicate": False}
    if not isinstance(event_data, dict):
        raise ValueError("Invalid Resend webhook payload.")

    provider_message_id = str(event_data.get("email_id") or "")
    if not provider_message_id:
        raise ValueError("Resend webhook is missing data.email_id.")
    occurred_at = parse_datetime(payload.get("created_at") or "")
    if occurred_at and timezone.is_naive(occurred_at):
        occurred_at = timezone.make_aware(occurred_at, datetime_timezone.utc)

    with transaction.atomic():
        event, created = DeliveryEvent.objects.get_or_create(
            provider_event_id=provider_event_id,
            defaults={
                "provider_message_id": provider_message_id,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "payload": payload,
            },
        )
        if event.delivery_id:
            return {"accepted": True, "ignored": False, "duplicate": not created}

        provider_message_id = event.provider_message_id

        delivery = (
            DeliveryRecord.objects.select_for_update()
            .select_related("contact")
            .filter(provider_message_id=provider_message_id)
            .first()
        )
        if delivery:
            _apply_delivery_event(delivery, event)
        return {
            "accepted": True,
            "ignored": False,
            "duplicate": not created,
            "matched": delivery is not None,
        }


def verify_resend_signature(*, raw_body, headers, secret):
    import base64
    import binascii
    import hmac
    import time

    if not secret or not secret.startswith("whsec_"):
        return False
    message_id = headers.get("svix-id")
    timestamp = headers.get("svix-timestamp")
    signature_header = headers.get("svix-signature")
    if not message_id or not timestamp or not signature_header:
        return False
    try:
        timestamp_number = int(timestamp)
        encoded_secret = secret.removeprefix("whsec_")
        encoded_secret += "=" * (-len(encoded_secret) % 4)
        signing_key = base64.b64decode(encoded_secret, validate=True)
    except (ValueError, binascii.Error):
        return False
    if abs(time.time() - timestamp_number) > 300:
        return False

    signed_content = (
        message_id.encode("utf-8")
        + b"."
        + timestamp.encode("utf-8")
        + b"."
        + raw_body
    )
    expected = base64.b64encode(
        hmac.new(signing_key, signed_content, hashlib.sha256).digest()
    ).decode("ascii")
    for value in signature_header.split():
        version, separator, candidate = value.partition(",")
        if separator and version == "v1" and hmac.compare_digest(candidate, expected):
            return True
    return False
