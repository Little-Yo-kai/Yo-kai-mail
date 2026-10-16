"""Safe, actionable generation errors, including wrapped provider exceptions."""

from django.conf import settings

from core.ai_fallback import is_rate_limit_error, is_temporary_unavailability_error
from core.generation_budget import GenerationCancelled, GenerationTimedOut

STAGE_LABELS = {
    "website_import": "reading the website",
    "brand_analysis": "understanding the brand",
    "reference_selection": "analysing the reference image",
    "content_plan": "planning the email",
    "email_design": "composing the email",
    "render": "rendering the email",
    "preview_assets": "preparing preview images",
}


def generation_failure(exc, *, stage=None, request_id=None):
    stage = getattr(exc, "stage", None) or stage or "website_import"
    chain = []
    current = exc
    while current is not None and id(current) not in {id(e) for e in chain}:
        chain.append(current)
        current = current.__cause__ or current.__context__
    text = " ".join(
        str(e) + " " + str(getattr(e, "details", "") or "") for e in chain
    ).lower()
    label = STAGE_LABELS.get(stage, stage.replace("_", " "))
    code, response_status = "generation_failed", 502
    message = f"Email generation failed while {label}. Please try again."
    if any(isinstance(e, (TimeoutError, GenerationTimedOut)) for e in chain) or any(
        marker in text for marker in ("timed out", "timeout", "deadline")
    ):
        code, response_status = "generation_timeout", 504
        message = f"Generation timed out while {label}. A provider took too long; please try again."
    elif any(isinstance(e, GenerationCancelled) for e in chain):
        code, response_status = "generation_cancelled", 409
        message = "Generation was cancelled."
    elif any(is_rate_limit_error(e) for e in chain) or is_rate_limit_error(
        RuntimeError(text)
    ):
        code, response_status = "provider_rate_limited", 429
        message = (
            "The provider's rate limit was reached. Please wait a moment and try again."
        )
    elif any(
        is_temporary_unavailability_error(e) for e in chain
    ) or is_temporary_unavailability_error(RuntimeError(text)):
        code, response_status = "provider_busy", 503
        message = "The AI provider is busy and could not complete this stage. Please try again shortly."
    elif "not configured" in text:
        code, response_status = "provider_not_configured", 503
        message = "Email generation is not configured on the server. Check the Firecrawl and Gemini API keys."
    payload = {
        "success": False,
        "stage": stage,
        "code": code,
        "error": message,
        "request_id": request_id,
    }
    if settings.DEBUG:
        payload["details"] = getattr(exc, "details", None) or str(exc)
    return payload, response_status
