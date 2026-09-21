import base64
import html
import re

from email_assets.temp_cache import (
    cleanup_expired_email_assets,
    get_or_cache_remote_image,
)


IMAGE_SRC_PATTERN = re.compile(r'src="([^"]+)"', re.IGNORECASE)


def build_preview_html(
    *,
    html_document: str,
    asset_inventory: list[dict],
) -> tuple[str, list[dict], list[dict]]:
    cleanup_expired_email_assets()

    asset_urls = {
        item.get("url")
        for item in asset_inventory
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    }

    source_urls = {
        html.unescape(match.group(1))
        for match in IMAGE_SRC_PATTERN.finditer(html_document)
    }

    replacements: dict[str, str] = {}
    diagnostics: list[dict] = []
    cached_assets: list[dict] = []

    for source_url in sorted(source_urls.intersection(asset_urls)):
        try:
            cached = get_or_cache_remote_image(source_url)
            encoded = base64.b64encode(cached.body).decode("ascii")
            replacements[source_url] = (
                f"data:{cached.mime_type};base64,{encoded}"
            )

            manifest = cached.public_manifest()
            cached_assets.append(manifest)
            diagnostics.append(
                {
                    "url": source_url,
                    "status": "embedded",
                    "mime_type": cached.mime_type,
                    "resolved_url": cached.resolved_url,
                    "bytes": len(cached.body),
                    "cache_key": cached.cache_key,
                    "cache_hit": cached.cache_hit,
                }
            )
        except Exception as exc:
            diagnostics.append(
                {
                    "url": source_url,
                    "status": "unavailable",
                    "reason": str(exc),
                }
            )

    def replace_src(match):
        raw_value = match.group(1)
        decoded_value = html.unescape(raw_value)
        replacement = replacements.get(decoded_value)
        if not replacement:
            return match.group(0)
        return f'src="{replacement}"'

    preview_html = IMAGE_SRC_PATTERN.sub(replace_src, html_document)
    return preview_html, diagnostics, cached_assets
