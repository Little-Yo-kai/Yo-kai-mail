from .schemas import AssetDescriptor, ContentPlan


def _append_asset(
    assets: list[AssetDescriptor],
    seen_ids: set[str],
    seen_urls: set[str],
    *,
    asset_id: str,
    kind: str,
    url: str | None,
    source: str,
) -> None:
    if not isinstance(url, str) or not url.strip():
        return

    url = url.strip()
    if asset_id in seen_ids or url in seen_urls:
        return

    asset = AssetDescriptor(
        asset_id=asset_id,
        kind=kind,
        url=url,
        source=source,
    )
    assets.append(asset)
    seen_ids.add(asset_id)
    seen_urls.add(url)


def build_asset_inventory(
    brand_profile: dict,
    available_assets: list[dict] | None = None,
) -> list[AssetDescriptor]:
    assets: list[AssetDescriptor] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()

    for item in available_assets or []:
        try:
            candidate = dict(item)
            candidate.setdefault("source", "request")
            asset = AssetDescriptor.model_validate(candidate)
        except Exception:
            continue

        _append_asset(
            assets,
            seen_ids,
            seen_urls,
            asset_id=asset.asset_id,
            kind=asset.kind,
            url=asset.url,
            source=asset.source,
        )

    brand_assets = brand_profile.get("assets") or {}

    _append_asset(
        assets,
        seen_ids,
        seen_urls,
        asset_id="logo_primary",
        kind="logo",
        url=brand_assets.get("primary_logo"),
        source="brand_profile",
    )

    _append_asset(
        assets,
        seen_ids,
        seen_urls,
        asset_id="og_image",
        kind="og",
        url=brand_assets.get("og_image"),
        source="brand_profile",
    )

    hero_index = 1
    for url in brand_assets.get("hero_candidates") or []:
        if not isinstance(url, str) or not url.strip() or url.strip() in seen_urls:
            continue

        _append_asset(
            assets,
            seen_ids,
            seen_urls,
            asset_id=f"hero_{hero_index}",
            kind="hero",
            url=url,
            source="brand_profile",
        )
        hero_index += 1

    return assets


def campaign_destination_url(campaign_brief: dict) -> str | None:
    destination = campaign_brief.get("destination_url")
    if isinstance(destination, str) and destination.strip():
        return destination.strip()

    product = campaign_brief.get("product") or {}
    product_url = product.get("url")
    if isinstance(product_url, str) and product_url.strip():
        return product_url.strip()

    return None


def normalize_content_plan(
    plan: ContentPlan,
    *,
    campaign_brief: dict,
    asset_inventory: list[AssetDescriptor],
) -> ContentPlan:
    plan.cta_strategy.destination_url = campaign_destination_url(campaign_brief)

    allowed_asset_ids = {asset.asset_id for asset in asset_inventory}
    for need in plan.asset_strategy:
        need.candidate_asset_ids = [
            asset_id
            for asset_id in need.candidate_asset_ids
            if asset_id in allowed_asset_ids
        ]

    return plan
