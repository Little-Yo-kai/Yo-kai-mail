import hashlib
import html as html_lib
import re

import resend
from django.conf import settings

from assets.services.ssrf import normalize_public_asset_url
from core.timing import timed_stage
from email_assets.temp_cache import (
    MIME_EXTENSIONS,
    EmailAssetCacheError,
    read_cached_email_asset,
)
from email_rendering.text import html_to_plain_text

IMAGE_TAG_PATTERN = re.compile(
    r'''<img\b(?:[^>"']|"[^"]*"|'[^']*')*>''', re.IGNORECASE,
)
ATTRIBUTE_PATTERN = re.compile(
    r'''\s+([^\s"'<>/=`]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>`]+)))?''',
)


def _image_sources(html_document: str):
    """Yield source spans while preserving the rest of the compiled HTML."""
    for tag_match in IMAGE_TAG_PATTERN.finditer(html_document):
        for attribute in ATTRIBUTE_PATTERN.finditer(tag_match.group(0)):
            if attribute.group(1).lower() != "src":
                continue
            for group in (2, 3, 4):
                if attribute.group(group) is not None:
                    start, end = attribute.span(group)
                    yield (
                        tag_match.start() + start,
                        tag_match.start() + end,
                        html_lib.unescape(attribute.group(group)),
                    )
                    break


class ResendNotConfiguredError(RuntimeError):
    pass


class ResendDeliveryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        details: str | None = None,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.details = details
        self.status_code = status_code


def _default_idempotency_key(
    *,
    to: str,
    subject: str,
    html: str,
) -> str:
    digest = hashlib.sha256(
        f"{to}\n{subject}\n{html}".encode("utf-8")
    ).hexdigest()
    return f"yo-kai-demo/{digest}"


def _prepare_inline_assets(
    *,
    html_document: str,
    cached_asset_refs: list[dict],
) -> tuple[str, list[dict], list[dict]]:
    sources = list(_image_sources(html_document))
    source_urls = {source_url for _, _, source_url in sources}

    replacement_map: dict[str, str] = {}
    attachments: list[dict] = []
    inline_manifest: list[dict] = []
    attachment_by_cache_key: dict[str, str] = {}
    total_bytes = 0

    for item in cached_asset_refs:
        cache_key = item["cache_key"]
        source_url = item["source_url"]

        if source_url not in source_urls:
            continue

        try:
            cached = read_cached_email_asset(
                cache_key,
                source_url=source_url,
            )
        except EmailAssetCacheError as exc:
            raise ResendDeliveryError(
                "A temporary email image is no longer available.",
                details=str(exc),
            ) from exc

        cid = attachment_by_cache_key.get(cache_key)

        if cid is None:
            if len(attachments) >= settings.EMAIL_ASSET_MAX_INLINE_COUNT:
                raise ResendDeliveryError("Too many inline email images.")
            if cached.mime_type not in MIME_EXTENSIONS or not cached.body:
                raise ResendDeliveryError("Cached email asset is not a supported image.")
            total_bytes += len(cached.body)
            if total_bytes > settings.EMAIL_ASSET_MAX_INLINE_BYTES:
                raise ResendDeliveryError(
                    "Cached email images exceed the inline attachment limit.",
                    details=(
                        f"Inline assets total {total_bytes} bytes; "
                        f"limit is {settings.EMAIL_ASSET_MAX_INLINE_BYTES}."
                    ),
                )

            cid = f"yokai-{cache_key[:24]}"
            attachment_by_cache_key[cache_key] = cid
            attachments.append(
                {
                    "filename": cached.filename,
                    "content": list(cached.body),
                    "content_type": cached.mime_type,
                    "content_id": cid,
                }
            )

        replacement_map[source_url] = f"cid:{cid}"
        inline_manifest.append(
            {
                "cache_key": cache_key,
                "source_url": source_url,
                "content_id": cid,
                "mime_type": cached.mime_type,
                "bytes": len(cached.body),
            }
        )

    parts: list[str] = []
    cursor = 0
    for start, end, source_url in sources:
        replacement = replacement_map.get(source_url)
        if not replacement:
            normalized_url = normalize_public_asset_url(source_url)
            if not normalized_url or (
                not settings.DEBUG and not normalized_url.startswith("https://")
            ):
                raise ResendDeliveryError(
                    "Email image must use a public HTTPS URL or a cached inline asset.",
                )
            replacement = html_lib.escape(normalized_url, quote=True)
        parts.extend((html_document[cursor:start], replacement))
        cursor = end
    parts.append(html_document[cursor:])
    return "".join(parts), attachments, inline_manifest


class ResendEmailService:
    def __init__(self):
        if not settings.RESEND_API_KEY:
            raise ResendNotConfiguredError(
                "RESEND_API_KEY is not configured."
            )

        if not settings.RESEND_FROM_EMAIL:
            raise ResendNotConfiguredError(
                "RESEND_FROM_EMAIL is not configured."
            )

    def send_test_email(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        cached_assets: list[dict] | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        resend.api_key = settings.RESEND_API_KEY

        delivery_html, attachments, inline_manifest = (
            _prepare_inline_assets(
                html_document=html,
                cached_asset_refs=cached_assets or [],
            )
        )

        key = idempotency_key or _default_idempotency_key(
            to=to,
            subject=subject,
            html=delivery_html,
        )

        params: resend.Emails.SendParams = {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [to],
            "subject": subject,
            "html": delivery_html,
            "text": html_to_plain_text(delivery_html),
        }

        if attachments:
            params["attachments"] = attachments

        try:
            options: resend.Emails.SendOptions = {
                "idempotency_key": key,
            }
            with timed_stage("send", provider="resend"):
                response = resend.Emails.send(
                    params,
                    options,
                )
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if not isinstance(status_code, int):
                status_code = getattr(exc, "status", None)
            if not isinstance(status_code, int):
                status_code = None

            raise ResendDeliveryError(
                "Resend could not send the email.",
                details=str(exc),
                status_code=status_code,
            ) from exc

        email_id = None
        if isinstance(response, dict):
            email_id = response.get("id")
        else:
            email_id = getattr(response, "id", None)

        if not email_id:
            raise ResendDeliveryError(
                "Resend returned a response without an email id."
            )

        return {
            "email_id": email_id,
            "provider": "resend",
            "to": to,
            "from": settings.RESEND_FROM_EMAIL,
            "idempotency_key": key,
            "inline_assets": inline_manifest,
            "inline_asset_count": len(attachments),
            "inline_asset_bytes": sum(
                len(item["content"]) for item in attachments
            ),
        }

    def send_campaign_email(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        idempotency_key: str,
    ) -> dict:
        """Send one recipient from a persisted campaign audience snapshot."""
        return self.send_test_email(
            to=to,
            subject=subject,
            html=html,
            cached_assets=[],
            idempotency_key=idempotency_key,
        )

    def get_email_status(self, *, email_id: str) -> dict:
        resend.api_key = settings.RESEND_API_KEY

        try:
            response = resend.Emails.get(email_id=email_id)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if not isinstance(status_code, int):
                status_code = getattr(exc, "status", None)
            if not isinstance(status_code, int):
                status_code = None

            raise ResendDeliveryError(
                "Resend could not retrieve email status.",
                details=str(exc),
                status_code=status_code,
            ) from exc

        if not isinstance(response, dict):
            response = dict(response)

        return {
            "email_id": response.get("id") or email_id,
            "provider": "resend",
            "last_event": response.get("last_event") or "unknown",
            "created_at": response.get("created_at"),
            "to": response.get("to") or [],
            "from": response.get("from"),
            "subject": response.get("subject"),
        }
