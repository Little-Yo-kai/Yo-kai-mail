"""Shared retry/fallback policy for transient Gemini capacity failures."""

import logging
import re
import time

from django.conf import settings

from core.generation_budget import current_budget, request_timeout

logger = logging.getLogger(__name__)
MAX_MODEL_ATTEMPTS = 3


def _http_status(exc: Exception) -> int | None:
    for name in ("status_code", "code"):
        value = str(getattr(exc, name, "")).strip().lower()
        if value == "service_unavailable":
            return 503
        if value == "too_many_requests":
            return 429
        if re.fullmatch(r"[1-5]\d{2}", value):
            return int(value)
    # Older SDKs expose status only in the message. Explicit errors take
    # precedence over phrases such as 'high demand'.
    match = re.search(
        r"\b(?:error code|status code|http status|http)\s*[:=]?\s*([1-5]\d{2})\b"
        r"|['\"]code['\"]\s*:\s*([1-5]\d{2})\b",
        str(exc).lower(),
    )
    return int(match.group(1) or match.group(2)) if match else None


def is_rate_limit_error(exc: Exception) -> bool:
    status = _http_status(exc)
    if status is not None:
        return status == 429
    text = str(exc).lower()
    return "rate limit" in text or "too_many_requests" in text


def is_temporary_unavailability_error(exc: Exception) -> bool:
    """Recognize provider 503 overload without masking invalid requests.

    Some google-genai SDK versions expose the status as an attribute and
    others only include it in their exception message.
    """
    status = _http_status(exc)
    if status is not None:
        return status == 503

    text = str(exc).lower()
    return "service_unavailable" in text or "high demand" in text


def call_with_model_fallback(
    create_call,
    *,
    primary_model: str,
    fallback_model: str | None = None,
    **kwargs,
):
    models: list[str] = []

    additional_models = getattr(settings, "GEMINI_ADDITIONAL_FALLBACK_MODELS", [])
    for candidate in (primary_model, fallback_model, *additional_models):
        if (
            isinstance(candidate, str)
            and candidate.strip()
            and candidate.strip() not in models
        ):
            models.append(candidate.strip())

    # Try another capacity pool instead of repeatedly hitting the overloaded
    # fallback. Keep the previous three-call ceiling, including any retry.
    models = models[:MAX_MODEL_ATTEMPTS]

    if not models:
        raise RuntimeError("No AI model is configured.")

    for index, model in enumerate(models):
        has_another_model = index < len(models) - 1
        # Try distinct models first. Only retry the final model when there
        # is room within the same fixed attempt limit.
        attempts = (
            2 if not has_another_model and len(models) < MAX_MODEL_ATTEMPTS else 1
        )

        for attempt in range(attempts):
            try:
                result = create_call(
                    model=model,
                    **{
                        **kwargs,
                        "timeout": request_timeout(
                            settings.GEMINI_REQUEST_TIMEOUT_SECONDS
                        ),
                    },
                )
                budget = current_budget()
                if budget is not None:
                    budget.check()
                return result
            except Exception as exc:
                overloaded = is_temporary_unavailability_error(exc)
                rate_limited = is_rate_limit_error(exc)
                if overloaded or rate_limited:
                    next_model = (
                        models[index + 1]
                        if has_another_model
                        else model
                        if overloaded and attempt + 1 < attempts
                        else None
                    )
                    logger.warning(
                        "Gemini capacity failure model=%s status=%s next_model=%s",
                        model,
                        503 if overloaded else 429,
                        next_model,
                    )
                if overloaded and attempt + 1 < attempts:
                    time.sleep(request_timeout(0.5))
                    continue

                if has_another_model and (rate_limited or overloaded):
                    break

                # Authentication, schema errors, and other failures are not
                # retried or disguised as model capacity issues.
                raise

    raise RuntimeError("AI request failed before a model was attempted.")
