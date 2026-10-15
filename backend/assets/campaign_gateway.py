"""Adapter between teammate-owned AssetRecord and the campaign gateway."""

from urllib.parse import urlparse

from campaigns.contracts import CampaignGatewayExecutionError
from campaigns.models import Campaign

from .models import AssetRecord
from .services.pipeline import process_asset
from .services.promotion import promote_asset


class CampaignAssetGateway:
    """Promote only the campaign's selected image descriptors."""

    def promote_campaign_assets(self, *, campaign_id, assets):
        campaign = Campaign.objects.get(pk=campaign_id)
        owner_scope = f"u:{campaign.owner_id}:campaign-{campaign.id}"

        promoted = []
        unresolved = []

        for descriptor in assets:
            source_url = descriptor.get("url")
            asset_id = descriptor.get("asset_id")
            kind = descriptor.get("kind")
            if not asset_id or not source_url:
                if asset_id:
                    unresolved.append(asset_id)
                continue

            try:
                record = (
                    AssetRecord.objects.filter(
                        owner_reference=owner_scope,
                        original_url=source_url,
                        status__in=[
                            AssetRecord.STATUS_TEMPORARY,
                            AssetRecord.STATUS_PERSISTENT,
                        ],
                    )
                    .order_by("-created_at")
                    .first()
                )

                if record is None:
                    record = AssetRecord.objects.create(
                        owner_reference=owner_scope,
                        original_url=source_url,
                        source="campaign_promotion",
                    )
                    process_asset(record)

                if record.status == AssetRecord.STATUS_TEMPORARY:
                    promote_asset(record)

                if record.status != AssetRecord.STATUS_PERSISTENT:
                    unresolved.append(asset_id)
                    continue

                url = record.stored_url or ""
                parsed = urlparse(url)
                if parsed.scheme != "https" or not parsed.hostname:
                    unresolved.append(asset_id)
                    continue

                promoted.append(
                    {
                        "asset_id": asset_id,
                        "asset_record_id": str(record.asset_id),
                        "kind": kind,
                        "public_url": url,
                    }
                )
            except Exception as exc:
                raise CampaignGatewayExecutionError(
                    "Asset storage or promotion failed.",
                    retryable=True,
                ) from exc

        return {
            "assets": promoted,
            "unresolved_asset_ids": unresolved,
        }
