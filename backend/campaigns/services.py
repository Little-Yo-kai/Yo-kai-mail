from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from demo_flow.service import generate_phase1_demo
from email_delivery.services.resend import ResendEmailService
from email_generation.schemas import EmailDesign
from email_rendering.compiler import compile_mjml_to_html
from email_rendering.renderer import render_email_to_mjml

from .models import (
    Campaign,
    CampaignDesignVersion,
    CampaignStatus,
    DesignVersionSource,
)


class CampaignTransitionError(ValueError):
    pass


class CampaignWorkflowError(ValueError):
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

    if (
        next_status
        in {
            CampaignStatus.GENERATED,
            CampaignStatus.REVIEWED,
            CampaignStatus.TEST_SENT,
            CampaignStatus.READY,
        }
        and campaign.active_design_id is None
    ):
        raise CampaignTransitionError(
            f"Campaign cannot enter {next_status} without an active EmailDesign."
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
    campaign.fact_ledger = result.get("fact_ledger") or {}
    campaign.asset_inventory = result.get("asset_inventory") or []

    campaign.save(
        update_fields=[
            "campaign_brief",
            "brand_profile",
            "reference",
            "content_plan",
            "fact_ledger",
            "asset_inventory",
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



EDITABLE_CAMPAIGN_STATUSES = {
    CampaignStatus.GENERATED,
    CampaignStatus.REVIEWED,
    CampaignStatus.TEST_SENT,
    CampaignStatus.READY,
    CampaignStatus.FAILED,
}


@transaction.atomic
def save_campaign_design(
    campaign: Campaign,
    *,
    email_design: dict,
    user,
) -> CampaignDesignVersion:
    if campaign.status not in EDITABLE_CAMPAIGN_STATUSES:
        raise CampaignWorkflowError(
            "Campaign design cannot be edited in its current state."
        )

    try:
        validated_design = EmailDesign.model_validate(email_design)
    except Exception as exc:
        raise CampaignWorkflowError(
            "EmailDesign does not satisfy the current schema."
        ) from exc

    version = create_design_version(
        campaign,
        email_design=validated_design.model_dump(mode="json"),
        user=user,
        source=DesignVersionSource.USER_EDIT,
    )

    if campaign.status != CampaignStatus.GENERATED:
        transition_campaign(
            campaign,
            next_status=CampaignStatus.GENERATED,
        )

    return version


def render_campaign_email(campaign: Campaign) -> dict:
    if campaign.active_design_id is None:
        raise CampaignWorkflowError(
            "Campaign has no active EmailDesign to render."
        )

    if not campaign.brand_profile:
        raise CampaignWorkflowError(
            "Campaign has no persisted BrandProfile."
        )

    render_result = render_email_to_mjml(
        brand_profile=campaign.brand_profile,
        email_design=campaign.active_design.email_design,
        asset_inventory=campaign.asset_inventory,
    )
    compile_result = compile_mjml_to_html(render_result["mjml"])

    return {
        "html": compile_result["html"],
        "mjml": render_result["mjml"],
        "compiler_errors": compile_result["compiler_errors"],
        "resolved_theme": render_result["resolved_theme"],
        "rendered_sections": render_result["rendered_sections"],
        "available_asset_ids": render_result["available_asset_ids"],
    }


@transaction.atomic
def send_campaign_test(
    campaign: Campaign,
    *,
    to: str,
    idempotency_key: str | None = None,
) -> dict:
    if campaign.status not in {
        CampaignStatus.GENERATED,
        CampaignStatus.REVIEWED,
        CampaignStatus.TEST_SENT,
        CampaignStatus.READY,
    }:
        raise CampaignWorkflowError(
            "Campaign is not in a state that can send a test email."
        )

    render_result = render_campaign_email(campaign)

    if campaign.status == CampaignStatus.GENERATED:
        transition_campaign(
            campaign,
            next_status=CampaignStatus.REVIEWED,
        )

    delivery = ResendEmailService().send_test_email(
        to=to,
        subject=campaign.active_design.email_design["subject"],
        html=render_result["html"],
        cached_assets=[],
        idempotency_key=idempotency_key,
    )

    if campaign.status == CampaignStatus.REVIEWED:
        transition_campaign(
            campaign,
            next_status=CampaignStatus.TEST_SENT,
        )
    elif campaign.status == CampaignStatus.TEST_SENT:
        campaign.test_sent_at = timezone.now()
        campaign.save(update_fields=["test_sent_at", "updated_at"])
    elif campaign.status == CampaignStatus.READY:
        campaign.test_sent_at = timezone.now()
        campaign.save(update_fields=["test_sent_at", "updated_at"])

    return {
        "delivery": delivery,
        "render": {
            "compiler_errors": render_result["compiler_errors"],
            "rendered_sections": render_result["rendered_sections"],
        },
    }
