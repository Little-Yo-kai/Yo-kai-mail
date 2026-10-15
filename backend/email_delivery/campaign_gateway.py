"""Domain adapters for campaign orchestration; no duplicate campaign routes."""

import hashlib

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max

from campaigns.contracts import CampaignGatewayExecutionError
from campaigns.models import Campaign, CampaignSendMode, CampaignStatus

from .models import (
    AudienceSnapshot,
    CampaignSendJob,
    CampaignSendJobStatus,
    DeliveryRecord,
    DeliveryRecordStatus,
)
from .services.campaigns import (
    CampaignDeliveryError,
    dispatch_campaign_send_job,
    resolve_campaign_audience as resolve_snapshot,
)


class ContactsAudienceGateway:
    def resolve_campaign_audience(self, *, campaign_id, owner_id, selection):
        from django.contrib.auth import get_user_model

        owner = get_user_model().objects.get(pk=owner_id)
        if (
            not isinstance(selection, dict)
            or not selection.get("list_ids") and not selection.get("contact_ids")
        ):
            raise CampaignGatewayExecutionError(
                "Choose at least one contact list or contact."
            )
        if not isinstance(selection.get("list_ids", []), list) or not isinstance(
            selection.get("contact_ids", []), list
        ):
            raise CampaignGatewayExecutionError(
                "Audience selection must contain lists of IDs."
            )

        try:
            result = resolve_snapshot(
                campaign_id=campaign_id,
                owner=owner,
                list_ids=selection.get("list_ids", []),
                contact_ids=selection.get("contact_ids", []),
            )
        except CampaignDeliveryError as exc:
            raise CampaignGatewayExecutionError(str(exc)) from exc

        return {
            "snapshot_id": result["snapshot_id"],
            "recipient_count": result["recipient_count"],
            "excluded_count": (
                result["excluded_status_count"]
                + result["excluded_consent_count"]
            ),
            "selection": {
                "list_ids": [str(value) for value in selection.get("list_ids", [])],
                "contact_ids": [str(value) for value in selection.get("contact_ids", [])],
            },
        }


class ResendCampaignDeliveryGateway:
    def create_campaign_delivery(
        self,
        *,
        campaign_id,
        audience_snapshot_id,
        subject,
        html,
        mode,
        scheduled_for,
        idempotency_key,
    ):
        if not settings.RESEND_CAMPAIGN_SEND_ENABLED:
            raise CampaignGatewayExecutionError(
                "Campaign delivery is not enabled.",
                retryable=True,
            )

        new_job = False
        with transaction.atomic():
            campaign = Campaign.objects.select_for_update().get(pk=campaign_id)
            expected_status = (
                CampaignStatus.SCHEDULED
                if mode == CampaignSendMode.SCHEDULED
                else CampaignStatus.SENDING
            )
            if campaign.status != expected_status:
                raise CampaignGatewayExecutionError(
                    "Campaign is not in its claimed delivery state."
                )

            try:
                snapshot = AudienceSnapshot.objects.get(
                    id=audience_snapshot_id,
                    campaign=campaign,
                    owner_id=campaign.owner_id,
                )
            except AudienceSnapshot.DoesNotExist as exc:
                raise CampaignGatewayExecutionError(
                    "Campaign audience snapshot is missing or invalid."
                ) from exc

            recipients = list(snapshot.recipients.select_related("contact"))
            if not recipients:
                raise CampaignGatewayExecutionError(
                    "Campaign audience contains no eligible recipients."
                )

            job = (
                CampaignSendJob.objects.select_for_update()
                .exclude(status=CampaignSendJobStatus.CANCELED)
                .filter(campaign=campaign)
                .first()
            )

            if job is not None:
                if (
                    job.audience_snapshot_id != audience_snapshot_id
                    or job.scheduled_for != scheduled_for
                ):
                    raise CampaignGatewayExecutionError(
                        "Another delivery job already exists for this campaign."
                    )
            else:
                job = CampaignSendJob.objects.create(
                    campaign=campaign,
                    owner_id=campaign.owner_id,
                    audience_snapshot=snapshot,
                    status=(
                        CampaignSendJobStatus.SCHEDULED
                        if mode == CampaignSendMode.SCHEDULED
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
                                + hashlib.sha256(
                                    recipient.normalized_email.encode("utf-8")
                                ).hexdigest()
                            ),
                        )
                        for recipient in recipients
                    ]
                )
                new_job = True

        if new_job:
            try:
                dispatch_campaign_send_job(job)
            except Exception as exc:
                raise CampaignGatewayExecutionError(
                    "The campaign delivery worker could not be queued.",
                    retryable=True,
                ) from exc

        return {
            "job_id": str(job.id),
            "mode": mode,
            "status": job.status,
            "scheduled_for": (
                job.scheduled_for.isoformat() if job.scheduled_for else None
            ),
        }

    def get_campaign_delivery_summary(self, *, campaign_id):
        queryset = DeliveryRecord.objects.filter(campaign_id=campaign_id)
        counts = {
            value["status"]: value["count"]
            for value in queryset.values("status").annotate(count=Count("id"))
        }
        return {
            "total": queryset.count(),
            "queued": counts.get(DeliveryRecordStatus.QUEUED, 0),
            "sent": counts.get(DeliveryRecordStatus.SENT, 0),
            "delivered": counts.get(DeliveryRecordStatus.DELIVERED, 0),
            "bounced": counts.get(DeliveryRecordStatus.BOUNCED, 0),
            "complained": counts.get(DeliveryRecordStatus.COMPLAINED, 0),
            "failed": counts.get(DeliveryRecordStatus.FAILED, 0),
            "last_event_at": queryset.aggregate(
                latest=Max("last_event_at")
            )["latest"],
        }
