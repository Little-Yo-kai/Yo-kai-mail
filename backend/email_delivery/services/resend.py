import hashlib

import resend
from django.conf import settings


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
        idempotency_key: str | None = None,
    ) -> dict:
        resend.api_key = settings.RESEND_API_KEY

        key = idempotency_key or _default_idempotency_key(
            to=to,
            subject=subject,
            html=html,
        )

        params: resend.Emails.SendParams = {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [to],
            "subject": subject,
            "html": html,
        }

        try:
            response = resend.Emails.send(
                params,
                idempotency_key=key,
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
        }
