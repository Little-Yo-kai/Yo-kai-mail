def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _public_image_urls(values):
    if not isinstance(values, list):
        return []

    return [
        value
        for value in values
        if isinstance(value, str)
        and value.startswith(("https://", "http://"))
    ]


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

    return {
        "schema_version": "1.0",
        "source": {
            "requested_url": requested_url,
            "resolved_url": (
                metadata.get("source_url")
                or metadata.get("url")
                or requested_url
            ),
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "language": metadata.get("language"),
            "status_code": metadata.get("status_code"),
        },
        "content": {
            "markdown": data.get("markdown") or "",
        },
        "visual": {
            "screenshot": data.get("screenshot"),
        },
        "assets": {
            "images": _public_image_urls(data.get("images")),
            "logo_candidate": (
                branding.get("logo")
                or branding_images.get("logo")
            ),
            "favicon": (
                branding_images.get("favicon")
                or metadata.get("favicon")
            ),
            "og_image": (
                branding_images.get("ogImage")
                or metadata.get("og_image")
                or metadata.get("og:image")
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
