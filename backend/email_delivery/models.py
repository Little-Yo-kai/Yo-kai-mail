import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


def normalize_email(value: str) -> str:
    return (value or "").strip().casefold()


class ContactStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PENDING_CONSENT = "pending_consent", "Pending consent"
    UNSUBSCRIBED = "unsubscribed", "Unsubscribed"
    BOUNCED = "bounced", "Bounced"
    SUPPRESSED = "suppressed", "Suppressed"
    COMPLAINED = "complained", "Complained"


class ConsentStatus(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    GRANTED = "granted", "Granted"
    WITHDRAWN = "withdrawn", "Withdrawn"


class Contact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="yokai_contacts",
    )
    email = models.EmailField(max_length=254)
    normalized_email = models.EmailField(max_length=254)
    first_name = models.CharField(max_length=120, blank=True)
    last_name = models.CharField(max_length=120, blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ContactStatus.choices,
        default=ContactStatus.PENDING_CONSENT,
        db_index=True,
    )
    consent_status = models.CharField(
        max_length=16,
        choices=ConsentStatus.choices,
        default=ConsentStatus.UNKNOWN,
        db_index=True,
    )
    consent_source = models.CharField(max_length=200, blank=True)
    consented_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["normalized_email"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "normalized_email"],
                name="unique_contact_email_per_owner",
            )
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="contact_owner_status_idx"),
            models.Index(fields=["owner", "consent_status"], name="contact_owner_consent_idx"),
        ]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip()
        self.normalized_email = normalize_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name or self.email


class ContactList(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="yokai_contact_lists",
    )
    name = models.CharField(max_length=160)
    normalized_name = models.CharField(max_length=160)
    description = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "normalized_name"],
                name="unique_contact_list_name_owner",
            )
        ]

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip()
        self.normalized_name = self.name.casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ContactListMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact_list = models.ForeignKey(
        ContactList,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="list_memberships",
    )
    source = models.CharField(max_length=100, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["added_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["contact_list", "contact"],
                name="unique_contact_membership",
            )
        ]

    def clean(self):
        if (
            self.contact_id
            and self.contact_list_id
            and self.contact.owner_id != self.contact_list.owner_id
        ):
            raise ValidationError(
                "A contact list can only contain contacts owned by its owner."
            )


class AudienceSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="yokai_audience_snapshots",
    )
    campaign = models.ForeignKey(
        "campaigns.Campaign",
        on_delete=models.CASCADE,
        related_name="audience_snapshots",
    )
    criteria = models.JSONField(default=dict, blank=True)
    recipient_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["campaign", "created_at"],
                name="aud_snapshot_created_idx",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Audience snapshots are immutable.")
        super().save(*args, **kwargs)


class AudienceSnapshotRecipient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snapshot = models.ForeignKey(
        AudienceSnapshot,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    contact = models.ForeignKey(
        Contact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audience_snapshot_entries",
    )
    contact_id_snapshot = models.UUIDField()
    email = models.EmailField(max_length=254)
    normalized_email = models.EmailField(max_length=254)
    display_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["normalized_email"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "normalized_email"],
                name="snapshot_recipient_email_uniq",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Audience snapshot recipients are immutable.")
        self.normalized_email = normalize_email(self.email)
        super().save(*args, **kwargs)


class CampaignSendJobStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    QUEUED = "queued", "Queued"
    SENDING = "sending", "Sending"
    SENT = "sent", "Sent"
    PARTIAL_FAILED = "partial_failed", "Partially failed"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Canceled"


class CampaignSendJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(
        "campaigns.Campaign",
        on_delete=models.CASCADE,
        related_name="delivery_jobs",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="yokai_campaign_send_jobs",
    )
    audience_snapshot = models.ForeignKey(
        AudienceSnapshot,
        on_delete=models.PROTECT,
        related_name="send_jobs",
    )
    status = models.CharField(
        max_length=20,
        choices=CampaignSendJobStatus.choices,
        default=CampaignSendJobStatus.QUEUED,
        db_index=True,
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_summary = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign"],
                condition=~Q(status=CampaignSendJobStatus.CANCELED),
                name="unique_active_campaign_job",
            )
        ]


class DeliveryRecordStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    SENT = "sent", "Sent"
    DELIVERY_DELAYED = "delivery_delayed", "Delivery delayed"
    DELIVERED = "delivered", "Delivered"
    BOUNCED = "bounced", "Bounced"
    FAILED = "failed", "Failed"
    COMPLAINED = "complained", "Complained"
    SUPPRESSED = "suppressed", "Suppressed"
    OPENED = "opened", "Opened"
    CLICKED = "clicked", "Clicked"
    CANCELED = "canceled", "Canceled"


class DeliveryRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        CampaignSendJob,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    campaign = models.ForeignKey(
        "campaigns.Campaign",
        on_delete=models.CASCADE,
        related_name="delivery_records",
    )
    audience_snapshot = models.ForeignKey(
        AudienceSnapshot,
        on_delete=models.PROTECT,
        related_name="delivery_records",
    )
    contact = models.ForeignKey(
        Contact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_records",
    )
    contact_id_snapshot = models.UUIDField()
    recipient_email = models.EmailField(max_length=254)
    normalized_email = models.EmailField(max_length=254)
    provider = models.CharField(max_length=32, default="resend")
    provider_message_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=24,
        choices=DeliveryRecordStatus.choices,
        default=DeliveryRecordStatus.QUEUED,
        db_index=True,
    )
    last_event_type = models.CharField(max_length=64, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempt = models.PositiveSmallIntegerField(default=1)
    idempotency_key = models.CharField(max_length=256, unique=True)
    failure_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["recipient_email"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "normalized_email"],
                name="unique_job_delivery_recipient",
            )
        ]
        indexes = [
            models.Index(fields=["campaign", "status"], name="delivery_campaign_status_idx"),
            models.Index(fields=["audience_snapshot", "normalized_email"], name="delivery_snapshot_email_idx"),
        ]


class DeliveryEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_event_id = models.CharField(max_length=255, unique=True)
    delivery = models.ForeignKey(
        DeliveryRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provider_events",
    )
    provider_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    event_type = models.CharField(max_length=64)
    occurred_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at", "created_at"]
        indexes = [
            models.Index(
                fields=["delivery", "event_type"],
                name="delivery_event_type_idx",
            )
        ]
