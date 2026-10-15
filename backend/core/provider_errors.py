from core.ai_fallback import is_rate_limit_error


def is_provider_rate_limited(
    exc: Exception,
    *,
    details: str | None = None,
) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True

    for candidate in (str(exc), details or ""):
        if not candidate:
            continue
        if is_rate_limit_error(RuntimeError(candidate)):
            return True

    return False
