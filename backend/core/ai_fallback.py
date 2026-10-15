"""Shared retry/fallback policy for transient Gemini capacity failures."""

import re
import time


def is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "rate limit" in text
        or "too_many_requests" in text
        or "error code: 429" in text
        or "'code': 429" in text
    )


def is_temporary_unavailability_error(exc: Exception) -> bool:
    """Recognize provider 503 overload without masking invalid requests.

    Some google-genai SDK versions expose the status as an attribute and
    others only include it in their exception message.
    """
    for attribute in ("status_code", "code"):
        code = getattr(exc, attribute, None)
        if str(code).strip().lower() in {"503", "service_unavailable"}:
            return True

    text = str(exc).lower()
    return (
        "service_unavailable" in text
        or "high demand" in text
        or bool(
            re.search(
                r"\b(?:error code|status code|http status|http)\s*[:=]?\s*503\b",
                text,
            )
        )
        or bool(re.search(r"['\"]code['\"]\s*:\s*503\b", text))
    )


def call_with_model_fallback(
    create_call,
    *,
    primary_model: str,
    fallback_model: str | None = None,
    **kwargs,
):
    models: list[str] = []

    for candidate in (primary_model, fallback_model):
        if (
            isinstance(candidate, str)
            and candidate.strip()
            and candidate.strip() not in models
        ):
            models.append(candidate.strip())

    if not models:
        raise RuntimeError("No AI model is configured.")

    for index, model in enumerate(models):
        has_another_model = index < len(models) - 1
        # Move immediately to the fallback on overload. If this is the last
        # available model, make just one delayed retry for transient 503s.
        attempts = 1 if has_another_model else 2

        for attempt in range(attempts):
            try:
                return create_call(
                    model=model,
                    **kwargs,
                )
            except Exception as exc:
                overloaded = is_temporary_unavailability_error(exc)
                if overloaded and attempt + 1 < attempts:
                    time.sleep(0.5)
                    continue

                if has_another_model and (
                    is_rate_limit_error(exc) or overloaded
                ):
                    break

                # Authentication, schema errors, and other failures are not
                # retried or disguised as model capacity issues.
                raise

    raise RuntimeError("AI request failed before a model was attempted.")
