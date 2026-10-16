import re

from assets.services.ssrf import normalize_public_asset_url


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _public_image_urls(values, base_url):
    if not isinstance(values, list):
        return []

    return list(dict.fromkeys(
        url for value in values
        if (url := normalize_public_asset_url(value, base_url))
    ))


def _first_image_url(base_url, *values):
    return next((
        url for value in values
        if (url := normalize_public_asset_url(value, base_url))
    ), None)


def build_website_snapshot(requested_url: str, firecrawl_data: dict) -> dict:
    """
    Normalize Firecrawl's provider-specific response into Yo-kai Mail's
    provider-independent WebsiteSnapshot contract.

    The snapshot stores observed evidence. It does not claim that detected
    branding is authoritative; Gemini will interpret this evidence later.
    """
    data = _as_dict(firecrawl_data)
    metadata = _as_dict(data.get("metadata"))
    branding = _as_dict(data.get("branding"))
    branding_images = _as_dict(branding.get("images"))
    resolved_url = (
        metadata.get("source_url")
        or metadata.get("sourceURL")
        or metadata.get("url")
        or requested_url
    )
    asset_base_url = (
        normalize_public_asset_url(resolved_url)
        or normalize_public_asset_url(requested_url)
    )

    # Product metadata is evidence for the campaign as well as for the brand.
    # Do not classify a homepage/article as a product merely from its URL.
    page_type = str(metadata.get("page_type") or metadata.get("og_type") or "").lower()
    product = None
    if page_type in {"product", "productsheet", "product.item"}:
        heading = re.search(r"^#\s+(.+)$", data.get("markdown") or "", re.MULTILINE)
        if heading:
            product = {
                "name": heading.group(1).strip()[:300],
                "description": str(metadata.get("og_description") or metadata.get("og:description") or "")[:1000],
                "url": requested_url,
            }

    return {
        "schema_version": "1.0",
        "source": {
            "requested_url": requested_url,
            "resolved_url": resolved_url,
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "language": metadata.get("language"),
            "status_code": metadata.get("status_code"),
        },
        "content": {
            "markdown": data.get("markdown") or "",
        },
        "product": product,
        "visual": {
            "screenshot": data.get("screenshot"),
        },
        "assets": {
            "images": _public_image_urls([
                *((data.get("images") or []) if isinstance(data.get("images"), list) else []),
                metadata.get("twitter:image"),
            ], asset_base_url),
            "logo_candidate": _first_image_url(
                asset_base_url, branding.get("logo"), branding_images.get("logo")
            ),
            "favicon": _first_image_url(
                asset_base_url, branding_images.get("favicon"), metadata.get("favicon")
            ),
            "og_image": _first_image_url(
                asset_base_url,
                branding_images.get("ogImage"),
                metadata.get("og_image"),
                metadata.get("og:image"),
            ),
        },
        "detected_branding": {
            "brand_name_candidate": branding.get("brand_name"),
            "color_scheme": branding.get("color_scheme"),
            "colors": _as_dict(branding.get("colors")),
            "fonts": (
                branding.get("fonts")
                if isinstance(branding.get("fonts"), list)
                else []
            ),
            "typography": _as_dict(branding.get("typography")),
            "spacing": _as_dict(branding.get("spacing")),
            "components": _as_dict(branding.get("components")),
            "personality": _as_dict(branding.get("personality")),
            "confidence": _as_dict(branding.get("confidence")),
        },
        "extraction": {
            "provider": "firecrawl",
            "scrape_id": metadata.get("scrape_id"),
            "credits_used": metadata.get("credits_used"),
            "proxy_used": metadata.get("proxy_used"),
        },
    }
