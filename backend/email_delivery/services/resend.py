import hashlib
import html as html_lib
import re

import resend
from django.conf import settings

from email_assets.temp_cache import (
    EmailAssetCacheError,
    read_cached_email_asset,
)


IMAGE_SRC_PATTERN = re.compile(r'src="([^"]+)"', re.IGNORECASE)


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
    source_urls = {
        html_lib.unescape(match.group(1))
        for match in IMAGE_SRC_PATTERN.finditer(html_document)
    }

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

    def replace_src(match):
        raw_value = match.group(1)
        decoded_value = html_lib.unescape(raw_value)
        replacement = replacement_map.get(decoded_value)
        if not replacement:
            return match.group(0)
        return f'src="{replacement}"'

    delivery_html = IMAGE_SRC_PATTERN.sub(replace_src, html_document)
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
        }

        if attachments:
            params["attachments"] = attachments

        try:
            options: resend.Emails.SendOptions = {
                "idempotency_key": key,
            }
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
