import base64
import html
import logging
import re
import time
from contextvars import copy_context
from queue import Empty, SimpleQueue
from threading import BoundedSemaphore, Thread

from django.conf import settings

from core.generation_budget import current_budget
from email_assets.temp_cache import (
    cleanup_expired_email_assets,
    get_or_cache_remote_image,
)

IMAGE_SRC_PATTERN = re.compile(r'src="([^"]+)"', re.IGNORECASE)
logger = logging.getLogger(__name__)
_preview_slots = BoundedSemaphore(4)


def build_preview_html(
    *,
    html_document: str,
    asset_inventory: list[dict],
) -> tuple[str, list[dict], list[dict]]:
    # DNS and filesystem operations are not covered by socket timeouts.
    # Bound the *whole* optional preview task so compiled HTML is returned
    # even if one of those operations stalls. At most four tasks may linger.
    budget = current_budget()
    seconds = settings.DEMO_PREVIEW_TIMEOUT_SECONDS
    if budget is not None:
        seconds = min(seconds, max(0, budget.remaining - 1))
    deadline = time.monotonic() + seconds

    def fallback():
        urls = {item.get("url") for item in asset_inventory if isinstance(item, dict)}
        diagnostics = [
            {
                "url": html.unescape(match.group(1)),
                "status": "unavailable",
                "reason": "Preview embedding did not finish in time. Original image URL retained.",
            }
            for match in IMAGE_SRC_PATTERN.finditer(html_document)
            if html.unescape(match.group(1)) in urls
        ]
        return html_document, diagnostics, []

    if seconds <= 0 or not _preview_slots.acquire(blocking=False):
        return fallback()
    results = SimpleQueue()
    context = copy_context()

    def work():
        try:
            results.put(
                context.run(
                    _build_preview_html,
                    html_document=html_document,
                    asset_inventory=asset_inventory,
                    deadline=deadline,
                )
            )
        except Exception:
            logger.exception("Preview cache failed; returning original email images")
            results.put(fallback())
        finally:
            _preview_slots.release()

    try:
        Thread(target=work, daemon=True, name="email-preview").start()
    except Exception:
        logger.exception(
            "Could not start preview caching; returning original email images"
        )
        _preview_slots.release()
        return fallback()
    try:
        return results.get(timeout=max(0, deadline - time.monotonic()))
    except Empty:
        return fallback()


def _build_preview_html(*, html_document, asset_inventory, deadline):
    budget = current_budget()
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
            remaining = deadline - time.monotonic()
            if (
                remaining <= 0
                or len(cached_assets) >= settings.EMAIL_ASSET_MAX_INLINE_COUNT
            ):
                raise TimeoutError(
                    "Preview embedding limit reached. Original image URL retained."
                )
            if budget is not None:
                budget.check()
            cached = get_or_cache_remote_image(source_url, timeout=min(2, remaining))
            encoded = base64.b64encode(cached.body).decode("ascii")
            replacements[source_url] = f"data:{cached.mime_type};base64,{encoded}"

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
        except Exception as exc:  # noqa: BLE001 -- Optional image failures must preserve the email.
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
