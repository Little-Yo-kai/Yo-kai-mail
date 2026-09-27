from django.conf import settings
from django.utils.module_loading import import_string


class CampaignGatewayUnavailable(RuntimeError):
    pass


GATEWAY_SETTINGS = {
    "assets": "CAMPAIGN_ASSET_PROMOTION_GATEWAY",
    "revision": "CAMPAIGN_DESIGN_REVISION_GATEWAY",
    "audience": "CAMPAIGN_AUDIENCE_GATEWAY",
    "delivery": "CAMPAIGN_DELIVERY_GATEWAY",
}


def load_campaign_gateway(kind: str):
    setting_name = GATEWAY_SETTINGS.get(kind)
    if not setting_name:
        raise CampaignGatewayUnavailable(
            f"Unknown campaign gateway kind: {kind}."
        )

    import_path = getattr(settings, setting_name, "")
    if not isinstance(import_path, str) or not import_path.strip():
        raise CampaignGatewayUnavailable(
            f"{setting_name} is not configured."
        )

    try:
        target = import_string(import_path.strip())
        gateway = target() if isinstance(target, type) else target
    except Exception as exc:
        raise CampaignGatewayUnavailable(
            f"{setting_name} could not be loaded."
        ) from exc

    if gateway is None:
        raise CampaignGatewayUnavailable(
            f"{setting_name} resolved to no gateway."
        )

    return gateway
