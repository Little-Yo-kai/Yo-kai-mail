import hashlib

from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone

from email_generation.schemas import EmailDesign

from .contracts import (
    AssetPromotionGateway,
    CampaignGatewayExecutionError,
    AssetPromotionResult,
    AudienceGateway,
    AudienceSnapshotContract,
    DeliveryGateway,
    DeliveryJobContract,
    DeliverySummaryContract,
    DesignRevisionGateway,
    DesignRevisionResult,
)
from .models import (
    Campaign,
    CampaignSendMode,
    CampaignStatus,
    DesignVersionSource,
)
from .services import (
    EDITABLE_CAMPAIGN_STATUSES,
    create_design_version,
    render_campaign_email,
    reset_campaign_after_design_change,
    transition_campaign,
)


class CampaignIntegrationError(ValueError):
    pass


def _validate_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _delivery_idempotency_key(
    campaign: Campaign,
    *,
    mode: str,
    scheduled_for,
) -> str:
    schedule_value = (
        scheduled_for.isoformat()
        if scheduled_for is not None
        else "immediate"
    )
    material = "|".join(
        [
            str(campaign.id),
            str(campaign.active_design_id),
            str(campaign.audience_snapshot_id),
            mode,
            schedule_value,
        ]
    )
    return "campaign-" + hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()


def _assert_delivery_assets_are_stable(campaign: Campaign) -> None:
    required_ids = _required_asset_ids(campaign)
    if not required_ids:
        return

    inventory_by_id = {
        item.get("asset_id"): item
        for item in campaign.asset_inventory
        if isinstance(item, dict) and item.get("asset_id")
    }

    missing = sorted(required_ids.difference(inventory_by_id))
    if missing:
        raise CampaignIntegrationError(
            "Campaign is missing required delivery assets: "
            + ", ".join(missing)
        )

    unstable = []
    for asset_id in sorted(required_ids):
        item = inventory_by_id[asset_id]
        if (
            item.get("source") != "asset_library"
            or not _validate_http_url(item.get("url", ""))
        ):
            unstable.append(asset_id)

    if unstable:
        raise CampaignIntegrationError(
            "Campaign assets must be promoted to stable public URLs "
            "before delivery: "
            + ", ".join(unstable)
        )


def _required_asset_ids(campaign: Campaign) -> set[str]:
    if campaign.active_design_id is None:
        raise CampaignIntegrationError(
            "Campaign has no active EmailDesign."
        )

    try:
        design = EmailDesign.model_validate(
            campaign.active_design.email_design
        )
    except Exception as exc:
        raise CampaignIntegrationError(
            "Campaign active EmailDesign is invalid."
        ) from exc

    required: set[str] = set()
    for section in design.sections:
        required.update(section.asset_ids)
        for item in section.items:
            if item.asset_id:
                required.add(item.asset_id)

    return required


def promote_campaign_assets(
    campaign: Campaign,
    *,
    gateway: AssetPromotionGateway,
) -> AssetPromotionResult:
    required_ids = _required_asset_ids(campaign)

    if not required_ids:
        return AssetPromotionResult()

    inventory_by_id = {
        item.get("asset_id"): item
        for item in campaign.asset_inventory
        if isinstance(item, dict) and item.get("asset_id")
    }
    missing = sorted(required_ids.difference(inventory_by_id))
    if missing:
        raise CampaignIntegrationError(
            "Campaign is missing required asset descriptors: "
            + ", ".join(missing)
        )

    source_assets = [
        inventory_by_id[asset_id]
        for asset_id in sorted(required_ids)
    ]

    try:
        raw_result = gateway.promote_campaign_assets(
            campaign_id=campaign.id,
            assets=source_assets,
        )
        result = AssetPromotionResult.model_validate(raw_result)
    except (CampaignIntegrationError, CampaignGatewayExecutionError):
        raise
    except Exception as exc:
        raise CampaignIntegrationError(
            "Asset promotion returned an invalid contract."
        ) from exc

    if result.unresolved_asset_ids:
        raise CampaignIntegrationError(
            "Asset promotion did not resolve all required assets: "
            + ", ".join(sorted(result.unresolved_asset_ids))
        )

    returned_ids = [asset.asset_id for asset in result.assets]
    if len(returned_ids) != len(set(returned_ids)):
        raise CampaignIntegrationError(
            "Asset promotion returned duplicate asset IDs."
        )

    if set(returned_ids) != required_ids:
        raise CampaignIntegrationError(
            "Asset promotion must return every required asset exactly once."
        )

    promoted_by_id = {asset.asset_id: asset for asset in result.assets}
    for asset_id, promoted in promoted_by_id.items():
        source = inventory_by_id[asset_id]
        if promoted.kind != source.get("kind"):
            raise CampaignIntegrationError(
                f"Asset kind changed during promotion for {asset_id}."
            )
        if not _validate_http_url(promoted.public_url):
            raise CampaignIntegrationError(
                f"Promoted asset {asset_id} does not have a public HTTP(S) URL."
            )

    updated_inventory = []
    for item in campaign.asset_inventory:
        if not isinstance(item, dict):
            updated_inventory.append(item)
            continue

        asset_id = item.get("asset_id")
        promoted = promoted_by_id.get(asset_id)
        if promoted is None:
            updated_inventory.append(item)
            continue

        replacement = dict(item)
        replacement["url"] = promoted.public_url
        replacement["source"] = "asset_library"
        replacement["asset_record_id"] = str(
            promoted.asset_record_id
        )
        updated_inventory.append(replacement)

    campaign.asset_inventory = updated_inventory
    campaign.save(update_fields=["asset_inventory", "updated_at"])
    return result


def revise_campaign_design(
    campaign: Campaign,
    *,
    gateway: DesignRevisionGateway,
    instruction: str,
    user,
):
    if campaign.status not in EDITABLE_CAMPAIGN_STATUSES:
        raise CampaignIntegrationError(
            "Campaign cannot be revised in its current state."
        )
    if campaign.active_design_id is None:
        raise CampaignIntegrationError(
            "Campaign has no active EmailDesign to revise."
        )

    instruction = instruction.strip()
    if not instruction:
        raise CampaignIntegrationError(
            "Revision instruction cannot be empty."
        )

    try:
        raw_result = gateway.revise_campaign_design(
            campaign_id=campaign.id,
            brand_profile=campaign.brand_profile,
            campaign_brief=campaign.campaign_brief,
            reference=campaign.reference,
            content_plan=campaign.content_plan,
            fact_ledger=campaign.fact_ledger,
            email_design=campaign.active_design.email_design,
            instruction=instruction,
        )
        result = DesignRevisionResult.model_validate(raw_result)
    except (CampaignIntegrationError, CampaignGatewayExecutionError):
        raise
    except Exception as exc:
        raise CampaignIntegrationError(
            "Design revision returned an invalid contract."
        ) from exc

    with transaction.atomic():
        version = create_design_version(
            campaign,
            email_design=result.email_design.model_dump(mode="json"),
            user=user,
            source=DesignVersionSource.REVISION,
        )
        reset_campaign_after_design_change(campaign)

    return version, result


def resolve_campaign_audience(
    campaign: Campaign,
    *,
    gateway: AudienceGateway,
    selection: dict,
) -> AudienceSnapshotContract:
    if campaign.status != CampaignStatus.READY:
        raise CampaignIntegrationError(
            "Audience can only be resolved for a ready campaign."
        )
    if not isinstance(selection, dict):
        raise CampaignIntegrationError(
            "Audience selection must be an object."
        )

    try:
        raw_result = gateway.resolve_campaign_audience(
            campaign_id=campaign.id,
            owner_id=campaign.owner_id,
            selection=selection,
        )
        result = AudienceSnapshotContract.model_validate(raw_result)
    except (CampaignIntegrationError, CampaignGatewayExecutionError):
        raise
    except Exception as exc:
        raise CampaignIntegrationError(
            "Audience resolution returned an invalid contract."
        ) from exc

    if result.recipient_count < 1:
        raise CampaignIntegrationError(
            "Audience snapshot contains no deliverable recipients."
        )

    campaign.audience_selection = result.selection or selection
    campaign.audience_snapshot_id = result.snapshot_id
    campaign.save(
        update_fields=[
            "audience_selection",
            "audience_snapshot_id",
            "updated_at",
        ]
    )
    return result


def queue_campaign_delivery(
    campaign: Campaign,
    *,
    gateway: DeliveryGateway,
    mode: str,
    scheduled_for=None,
    idempotency_key: str | None = None,
) -> DeliveryJobContract:
    if campaign.status != CampaignStatus.READY:
        raise CampaignIntegrationError(
            "Campaign must be ready before delivery can be queued."
        )
    if campaign.audience_snapshot_id is None:
        raise CampaignIntegrationError(
            "Campaign must have an immutable audience snapshot before sending."
        )

    if mode not in {
        CampaignSendMode.SEND_NOW,
        CampaignSendMode.SCHEDULED,
    }:
        raise CampaignIntegrationError("Invalid campaign send mode.")

    if mode == CampaignSendMode.SCHEDULED:
        if scheduled_for is None:
            raise CampaignIntegrationError(
                "scheduled_for is required for scheduled delivery."
            )
        if scheduled_for <= timezone.now():
            raise CampaignIntegrationError(
                "scheduled_for must be in the future."
            )
    else:
        scheduled_for = None

    _assert_delivery_assets_are_stable(campaign)
    render_result = render_campaign_email(campaign)

    effective_idempotency_key = (
        idempotency_key
        or _delivery_idempotency_key(
            campaign,
            mode=mode,
            scheduled_for=scheduled_for,
        )
    )

    try:
        raw_result = gateway.create_campaign_delivery(
            campaign_id=campaign.id,
            audience_snapshot_id=campaign.audience_snapshot_id,
            subject=campaign.active_design.email_design["subject"],
            html=render_result["html"],
            mode=mode,
            scheduled_for=scheduled_for,
            idempotency_key=effective_idempotency_key,
        )
        result = DeliveryJobContract.model_validate(raw_result)
    except (CampaignIntegrationError, CampaignGatewayExecutionError):
        raise
    except Exception as exc:
        raise CampaignIntegrationError(
            "Delivery creation returned an invalid contract."
        ) from exc

    if result.mode != mode:
        raise CampaignIntegrationError(
            "Delivery job mode does not match the campaign request."
        )

    campaign.send_mode = mode
    campaign.scheduled_for = scheduled_for
    campaign.save(
        update_fields=[
            "send_mode",
            "scheduled_for",
            "updated_at",
        ]
    )

    transition_campaign(
        campaign,
        next_status=(
            CampaignStatus.SCHEDULED
            if mode == CampaignSendMode.SCHEDULED
            else CampaignStatus.SENDING
        ),
    )
    return result


def get_campaign_delivery_summary(
    campaign: Campaign,
    *,
    gateway: DeliveryGateway,
) -> DeliverySummaryContract:
    try:
        raw_result = gateway.get_campaign_delivery_summary(
            campaign_id=campaign.id,
        )
        return DeliverySummaryContract.model_validate(raw_result)
    except CampaignGatewayExecutionError:
        raise
    except Exception as exc:
        raise CampaignIntegrationError(
            "Delivery summary returned an invalid contract."
        ) from exc
