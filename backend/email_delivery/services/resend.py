import base64
import hashlib
import time

import resend
from django.conf import settings

from assets.services.ssrf import normalize_public_asset_url
from core.timing import timed_stage
from email_assets.html import image_sources, replace_image_sources
from email_assets.temp_cache import (
    MIME_EXTENSIONS,
    CachedEmailAsset,
    EmailAssetCacheError,
    get_or_cache_remote_image,
    read_cached_email_asset,
)
from email_rendering.text import html_to_plain_text


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
        f"{to}\n{subject}\n{html}".encode()
    ).hexdigest()
    return f"yo-kai-demo/{digest}"


def _prepare_inline_assets(
    *,
    html_document: str,
    cached_asset_refs: list[dict],
) -> tuple[str, list[dict], list[dict]]:
    source_urls = image_sources(html_document)
    if len(source_urls) > settings.EMAIL_ASSET_MAX_INLINE_COUNT:
        raise ResendDeliveryError("Too many inline images for one email.")

    replacement_map: dict[str, str] = {}
    attachments: list[dict] = []
    inline_manifest: list[dict] = []
    attachment_by_cache_key: dict[str, str] = {}
    prepared_assets: dict[str, CachedEmailAsset] = {}
    total_bytes = 0

    supplied_urls = {item["source_url"] for item in cached_asset_refs}
    refs = list(cached_asset_refs)
    deadline = time.monotonic() + 10
    # A missing client manifest must not silently turn an image email into
    # a hotlinked email. Campaign delivery also uses this path.
    for source_url in sorted(source_urls - supplied_urls):
        if not normalize_public_asset_url(source_url):
            raise ResendDeliveryError(
                "Email image must use a public URL or a cached inline asset.",
            )
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EmailAssetCacheError("Image download time limit reached.")
            cached = get_or_cache_remote_image(source_url, timeout=min(5, remaining))
        except (EmailAssetCacheError, OSError, ValueError) as exc:
            raise ResendDeliveryError(
                "An email image could not be attached. Replace the image or regenerate before sending.",
                details=str(exc),
            ) from exc
        prepared_assets[cached.cache_key] = cached
        refs.append({"cache_key": cached.cache_key, "source_url": source_url})

    for item in refs:
        cache_key = item["cache_key"]
        source_url = item["source_url"]

        if source_url not in source_urls:
            continue

        cached = prepared_assets.get(cache_key)
        if cached is None:
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
            # A legacy entry may acquire a new key after image normalization.
            prepared_assets[cache_key] = cached
            prepared_assets[cached.cache_key] = cached

        cache_key = cached.cache_key

        cid = attachment_by_cache_key.get(cache_key)

        if cid is None:
            if len(attachments) >= settings.EMAIL_ASSET_MAX_INLINE_COUNT:
                raise ResendDeliveryError("Too many inline images for one email.")
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
                    "content": base64.b64encode(cached.body).decode("ascii"),
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

    # Retrying equivalent HTML with reordered client refs must produce the same
    # provider payload for the same idempotency key.
    attachments.sort(key=lambda item: item["content_id"])
    delivery_html = replace_image_sources(html_document, replacement_map)
    return delivery_html, attachments, inline_manifest


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
                {item["content_id"]: item["bytes"] for item in inline_manifest}.values()
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
