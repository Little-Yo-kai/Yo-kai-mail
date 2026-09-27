from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from demo_flow.service import generate_phase1_demo

from .models import (
    Campaign,
    CampaignDesignVersion,
    CampaignStatus,
    DesignVersionSource,
)


class CampaignTransitionError(ValueError):
    pass


def _status_timestamp_field(status: str) -> str | None:
    return {
        CampaignStatus.GENERATED: "generated_at",
        CampaignStatus.REVIEWED: "reviewed_at",
        CampaignStatus.TEST_SENT: "test_sent_at",
        CampaignStatus.READY: "ready_at",
        CampaignStatus.SENDING: "sending_at",
        CampaignStatus.SENT: "sent_at",
        CampaignStatus.FAILED: "failed_at",
    }.get(status)


@transaction.atomic
def transition_campaign(
    campaign: Campaign,
    *,
    next_status: str,
) -> Campaign:
    if campaign.status == next_status:
        return campaign

    if not campaign.can_transition_to(next_status):
        raise CampaignTransitionError(
            f"Campaign cannot transition from {campaign.status} "
            f"to {next_status}."
        )

    campaign.status = next_status
    timestamp_field = _status_timestamp_field(next_status)
    update_fields = ["status", "updated_at"]

    if timestamp_field:
        setattr(campaign, timestamp_field, timezone.now())
        update_fields.append(timestamp_field)

    campaign.save(update_fields=update_fields)
    return campaign


def create_design_version(
    campaign: Campaign,
    *,
    email_design: dict,
    user,
    source: str = DesignVersionSource.GENERATED,
) -> CampaignDesignVersion:
    current_max = (
        campaign.design_versions.aggregate(max_version=Max("version"))[
            "max_version"
        ]
        or 0
    )

    version = CampaignDesignVersion.objects.create(
        campaign=campaign,
        version=current_max + 1,
        source=source,
        email_design=email_design,
        created_by=user,
    )

    campaign.active_design = version
    campaign.save(update_fields=["active_design", "updated_at"])
    return version


@transaction.atomic
def generate_campaign(
    campaign: Campaign,
    *,
    user,
    reference_image=None,
) -> Campaign:
    result = generate_phase1_demo(
        url=campaign.source_url,
        reference_image=reference_image,
        additional_instructions=campaign.additional_instructions,
    )

    campaign.campaign_brief = result.get("campaign_brief") or {}
    campaign.brand_profile = result.get("brand_profile") or {}
    campaign.reference = result.get("reference") or {}
    campaign.content_plan = result.get("content_plan") or {}

    campaign.save(
        update_fields=[
            "campaign_brief",
            "brand_profile",
            "reference",
            "content_plan",
            "updated_at",
        ]
    )

    create_design_version(
        campaign,
        email_design=result["email_design"],
        user=user,
        source=DesignVersionSource.GENERATED,
    )

    if campaign.status != CampaignStatus.GENERATED:
        if campaign.status == CampaignStatus.DRAFT:
            transition_campaign(
                campaign,
                next_status=CampaignStatus.GENERATED,
            )
        elif campaign.can_transition_to(CampaignStatus.GENERATED):
            transition_campaign(
                campaign,
                next_status=CampaignStatus.GENERATED,
            )
        else:
            raise CampaignTransitionError(
                "Campaign cannot be regenerated from its current state."
            )

    return campaign
