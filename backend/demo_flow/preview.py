import base64
import html
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

from email_rendering.screenshot import _detect_image_mime, _host_is_public


MAX_PREVIEW_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3
IMAGE_SRC_PATTERN = re.compile(r'src="([^"]+)"', re.IGNORECASE)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_public_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and _host_is_public(parsed.hostname)
    )


def _detect_preview_mime(body: bytes, content_type: str | None) -> str | None:
    detected = _detect_image_mime(body)
    if detected:
        return detected

    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    stripped = body.lstrip()

    if normalized == "image/svg+xml" and (
        stripped.startswith(b"<svg")
        or stripped.startswith(b"<?xml")
    ):
        return "image/svg+xml"

    return None


def _fetch_public_image(url: str) -> tuple[bytes, str, str]:
    current_url = url
    opener = urllib.request.build_opener(_NoRedirect())

    for _ in range(MAX_REDIRECTS + 1):
        if not _safe_public_http_url(current_url):
            raise ValueError("Image URL is not a safe public HTTP(S) destination.")

        request = urllib.request.Request(
            current_url,
            headers={
                "User-Agent": "Yo-kai-Mail-Demo/1.0",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
            method="GET",
        )

        try:
            response = opener.open(request, timeout=8)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                if not location:
                    raise ValueError(
                        f"Image redirect returned HTTP {exc.code} without Location."
                    ) from exc
                current_url = urljoin(current_url, location)
                continue

            raise ValueError(f"Image request returned HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"Image request failed: {exc.reason}") from exc

        content_type = response.headers.get("Content-Type")
        body = response.read(MAX_PREVIEW_IMAGE_BYTES + 1)

        if len(body) > MAX_PREVIEW_IMAGE_BYTES:
            raise ValueError("Image exceeds the 8 MB demo preview limit.")

        mime_type = _detect_preview_mime(body, content_type)
        if not mime_type:
            raise ValueError(
                "Remote response was not a supported image."
            )

        return body, mime_type, current_url

    raise ValueError("Image exceeded the maximum redirect count.")


def build_preview_html(
    *,
    html_document: str,
    asset_inventory: list[dict],
) -> tuple[str, list[dict]]:
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

    for source_url in sorted(source_urls.intersection(asset_urls)):
        try:
            body, mime_type, resolved_url = _fetch_public_image(source_url)
            encoded = base64.b64encode(body).decode("ascii")
            replacements[source_url] = f"data:{mime_type};base64,{encoded}"
            diagnostics.append(
                {
                    "url": source_url,
                    "status": "embedded",
                    "mime_type": mime_type,
                    "resolved_url": resolved_url,
                    "bytes": len(body),
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

    return IMAGE_SRC_PATTERN.sub(replace_src, html_document), diagnostics
