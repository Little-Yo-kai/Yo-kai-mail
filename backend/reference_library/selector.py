from .library import REFERENCE_LIBRARY


def _normalize_text(value) -> str:
    return str(value or "").strip().lower()


def _available_image_count(brand_profile: dict) -> int:
    assets = brand_profile.get("assets") or {}
    urls = []

    og_image = assets.get("og_image")
    if isinstance(og_image, str) and og_image:
        urls.append(og_image)

    for value in assets.get("hero_candidates") or []:
        if isinstance(value, str) and value:
            urls.append(value)

    return len(set(urls))


def _tone_values(brand_profile: dict) -> set[str]:
    communication = brand_profile.get("communication") or {}
    values = communication.get("tone") or []
    return {
        _normalize_text(value)
        for value in values
        if _normalize_text(value)
    }


def _industry_matches(industry: str, tags: list[str]) -> list[str]:
    if not industry:
        return []

    return [
        tag
        for tag in tags
        if tag != "general" and tag in industry
    ]


def _score_reference(
    reference: dict,
    brand_profile: dict,
    campaign_brief: dict,
) -> tuple[float, list[str], dict]:
    score = 0.0
    reasons = []

    campaign_type = _normalize_text(campaign_brief.get("campaign_type"))
    goal = _normalize_text(campaign_brief.get("goal"))
    industry = _normalize_text(
        (brand_profile.get("identity") or {}).get("industry")
    )
    tones = _tone_values(brand_profile)

    if campaign_type in reference["campaign_types"]:
        score += 6.0
        reasons.append(f"Matches campaign type: {campaign_type}.")

    if goal in reference["goals"]:
        score += 4.0
        reasons.append(f"Supports campaign goal: {goal}.")

    matching_industries = _industry_matches(
        industry,
        reference["industries"],
    )
    if matching_industries:
        score += 4.0
        reasons.append(
            "Matches brand industry: "
            + ", ".join(sorted(matching_industries))
            + "."
        )

    tone_overlap = tones.intersection(reference["tone_tags"])
    if tone_overlap:
        score += min(len(tone_overlap), 3) * 1.5
        reasons.append(
            "Matches brand tone: "
            + ", ".join(sorted(tone_overlap))
            + "."
        )

    offer = campaign_brief.get("offer") or {}
    offer_type = _normalize_text(offer.get("type")) or "none"
    has_offer = offer_type != "none"

    if has_offer and reference["supports_offer"]:
        score += 3.0
        reasons.append("Layout supports a promotional offer.")
    elif has_offer and not reference["supports_offer"]:
        score -= 1.5

    product = campaign_brief.get("product")
    if reference["requires_product"]:
        if product:
            score += 2.0
            reasons.append("Layout is appropriate for a defined product.")
        else:
            score -= 8.0

    available_images = _available_image_count(brand_profile)
    minimum_images = reference["min_images"]
    sufficient_images = available_images >= minimum_images

    if sufficient_images:
        score += 2.0
        reasons.append(
            f"Current assets can support the layout ({available_images} "
            f"available, {minimum_images} recommended)."
        )
    else:
        shortage = minimum_images - available_images
        score -= min(shortage * 1.5, 6.0)
        reasons.append(
            f"Asset-light fallback may be needed ({available_images} "
            f"available, {minimum_images} recommended)."
        )

    if reference["recipe_family"] == "general_story":
        score += 0.5

    asset_fit = {
        "available_image_count": available_images,
        "minimum_recommended_images": minimum_images,
        "sufficient_images": sufficient_images,
    }

    return score, reasons, asset_fit


def select_reference(
    brand_profile: dict,
    campaign_brief: dict,
) -> dict:
    ranked = []

    for index, reference in enumerate(REFERENCE_LIBRARY):
        score, reasons, asset_fit = _score_reference(
            reference,
            brand_profile,
            campaign_brief,
        )
        ranked.append((score, -index, reference, reasons, asset_fit))

    _, _, selected, reasons, asset_fit = max(
        ranked,
        key=lambda item: (item[0], item[1]),
    )

    return {
        "schema_version": "1.0",
        "source": "internal_library",
        "reference_id": selected["reference_id"],
        "name": selected["name"],
        "recipe_family": selected["recipe_family"],
        "selection_reasons": reasons,
        "asset_fit": asset_fit,
        "reference_design_spec": selected["spec"],
    }
