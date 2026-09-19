from .schemas import BrandAnalysis, BrandAssets, BrandProfile


def _unique_public_urls(values):
    seen = set()
    result = []

    for value in values:
        if not isinstance(value, str):
            continue
        if not value.startswith(("https://", "http://")):
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)

    return result


def build_brand_profile(snapshot: dict, analysis: BrandAnalysis) -> BrandProfile:
    assets = snapshot.get("assets") or {}
    hero_candidates = _unique_public_urls(
        [assets.get("og_image"), *(assets.get("images") or [])]
    )[:8]

    return BrandProfile(
        identity=analysis.identity,
        visual=analysis.visual,
        communication=analysis.communication,
        confidence=analysis.confidence,
        assets=BrandAssets(
            primary_logo=assets.get("logo_candidate"),
            hero_candidates=hero_candidates,
            og_image=assets.get("og_image"),
            favicon=assets.get("favicon"),
        ),
    )
