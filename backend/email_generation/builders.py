from .schemas import AssetDescriptor, ContentPlan, FactLedger


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



def build_fact_ledger(
    brand_profile: dict,
    campaign_brief: dict,
) -> FactLedger:
    identity = brand_profile.get("identity") or {}
    product = campaign_brief.get("product") or {}
    offer = campaign_brief.get("offer") or {}

    verified_facts: list[str] = []

    brand_name = identity.get("name")
    if isinstance(brand_name, str) and brand_name.strip():
        verified_facts.append(f"Brand: {brand_name.strip()}")

    product_name = product.get("name")
    if isinstance(product_name, str) and product_name.strip():
        verified_facts.append(f"Product name: {product_name.strip()}")

    product_description = product.get("description")
    if isinstance(product_description, str) and product_description.strip():
        verified_facts.append(
            "Product description evidence: " + product_description.strip()
        )

    offer_facts: list[str] = []
    offer_type = offer.get("type")
    if isinstance(offer_type, str) and offer_type and offer_type != "none":
        offer_facts.append(f"Offer type: {offer_type}")

        for key, label in (
            ("value", "Offer value"),
            ("code", "Offer code"),
            ("details", "Offer details"),
        ):
            value = offer.get(key)
            if isinstance(value, str) and value.strip():
                offer_facts.append(f"{label}: {value.strip()}")

    return FactLedger(
        brand_name=brand_name.strip() if isinstance(brand_name, str) else None,
        product_name=(
            product_name.strip()
            if isinstance(product_name, str)
            else None
        ),
        verified_facts=verified_facts,
        offer_facts=offer_facts,
        authoritative_destination_url=campaign_destination_url(campaign_brief),
        forbidden_claim_categories=[
            "price unless explicitly present in the campaign brief",
            "availability or stock status unless explicitly present",
            "deadlines or urgency unless explicitly present",
            "discounts or promotions unless explicitly present",
            "materials, dimensions, features, or craftsmanship details beyond provided evidence",
            "statistics, guarantees, certifications, awards, or testimonials not provided",
        ],
    )



def normalize_email_design(
    design,
    *,
    asset_inventory: list[AssetDescriptor],
    fact_ledger: FactLedger,
):
    allowed_asset_ids = {asset.asset_id for asset in asset_inventory}
    authoritative_url = fact_ledger.authoritative_destination_url

    seen_ids: set[str] = set()
    normalized_sections = []

    for index, section in enumerate(
        sorted(design.sections, key=lambda item: item.order),
        start=1,
    ):
        section.order = index

        if section.id in seen_ids:
            candidate_id = f"{section.type}_{index}"
            suffix = 2
            while candidate_id in seen_ids:
                candidate_id = f"{section.type}_{index}_{suffix}"
                suffix += 1
            section.id = candidate_id
        seen_ids.add(section.id)

        section.asset_ids = [
            asset_id
            for asset_id in section.asset_ids
            if asset_id in allowed_asset_ids
        ]

        if section.cta is not None:
            section.cta.url = authoritative_url

        for item in section.items:
            if item.asset_id not in allowed_asset_ids:
                item.asset_id = None

            if item.cta is not None:
                item.cta.url = authoritative_url

        normalized_sections.append(section)

    design.sections = normalized_sections
    return design
