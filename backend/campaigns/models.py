import uuid

from django.conf import settings
from django.db import models


class CampaignStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    GENERATED = "generated", "Generated"
    REVIEWED = "reviewed", "Reviewed"
    TEST_SENT = "test_sent", "Test sent"
    READY = "ready", "Ready"
    SCHEDULED = "scheduled", "Scheduled"
    SENDING = "sending", "Sending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class CampaignReferenceMode(models.TextChoices):
    AUTOMATIC = "automatic", "Automatic"
    UPLOADED = "uploaded", "Uploaded"


class CampaignSendMode(models.TextChoices):
    NONE = "none", "Not selected"
    SEND_NOW = "send_now", "Send now"
    SCHEDULED = "scheduled", "Scheduled"


class DesignVersionSource(models.TextChoices):
    GENERATED = "generated", "Generated"
    USER_EDIT = "user_edit", "User edit"
    REVISION = "revision", "Revision"


ALLOWED_CAMPAIGN_TRANSITIONS = {
    CampaignStatus.DRAFT: {CampaignStatus.GENERATED},
    CampaignStatus.GENERATED: {
        CampaignStatus.REVIEWED,
        CampaignStatus.FAILED,
    },
    CampaignStatus.REVIEWED: {
        CampaignStatus.TEST_SENT,
        CampaignStatus.READY,
        CampaignStatus.GENERATED,
        CampaignStatus.FAILED,
    },
    CampaignStatus.TEST_SENT: {
        CampaignStatus.READY,
        CampaignStatus.GENERATED,
        CampaignStatus.FAILED,
    },
    CampaignStatus.READY: {
        CampaignStatus.SCHEDULED,
        CampaignStatus.SENDING,
        CampaignStatus.GENERATED,
        CampaignStatus.FAILED,
    },
    CampaignStatus.SCHEDULED: {
        CampaignStatus.SENDING,
        CampaignStatus.READY,
        CampaignStatus.FAILED,
    },
    CampaignStatus.SENDING: {
        CampaignStatus.SENT,
        CampaignStatus.FAILED,
    },
    CampaignStatus.SENT: set(),
    CampaignStatus.FAILED: {
        CampaignStatus.GENERATED,
        CampaignStatus.READY,
    },
}


class Campaign(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="yokai_campaigns",
    )
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=32,
        choices=CampaignStatus.choices,
        default=CampaignStatus.DRAFT,
        db_index=True,
    )
    source_url = models.URLField(max_length=2048)
    reference_mode = models.CharField(
        max_length=16,
        choices=CampaignReferenceMode.choices,
        default=CampaignReferenceMode.AUTOMATIC,
    )
    additional_instructions = models.TextField(blank=True)

    campaign_brief = models.JSONField(default=dict, blank=True)
    brand_profile = models.JSONField(default=dict, blank=True)
    reference = models.JSONField(default=dict, blank=True)
    content_plan = models.JSONField(default=dict, blank=True)
    fact_ledger = models.JSONField(default=dict, blank=True)
    asset_inventory = models.JSONField(default=list, blank=True)

    active_design = models.ForeignKey(
        "CampaignDesignVersion",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )

    audience_selection = models.JSONField(default=dict, blank=True)
    audience_snapshot_id = models.UUIDField(null=True, blank=True)

    send_mode = models.CharField(
        max_length=16,
        choices=CampaignSendMode.choices,
        default=CampaignSendMode.NONE,
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)

    generated_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    test_sent_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    sending_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Campaign {self.id}"

    def can_transition_to(self, next_status: str) -> bool:
        return next_status in ALLOWED_CAMPAIGN_TRANSITIONS.get(
            self.status,
            set(),
        )


class CampaignDesignVersion(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="design_versions",
    )
    version = models.PositiveIntegerField()
    source = models.CharField(
        max_length=16,
        choices=DesignVersionSource.choices,
        default=DesignVersionSource.GENERATED,
    )
    email_design = models.JSONField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "version"],
                name="unique_campaign_design_version",
            )
        ]

    def __str__(self):
        return f"{self.campaign_id} v{self.version}"
