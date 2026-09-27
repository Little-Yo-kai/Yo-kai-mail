def is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "rate limit" in text
        or "too_many_requests" in text
        or "error code: 429" in text
        or "'code': 429" in text
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

    last_error: Exception | None = None

    for index, model in enumerate(models):
        try:
            return create_call(
                model=model,
                **kwargs,
            )
        except Exception as exc:
            last_error = exc

            has_another_model = index < len(models) - 1
            if not is_rate_limit_error(exc) or not has_another_model:
                raise

    if last_error is not None:
        raise last_error

    raise RuntimeError("AI request failed before a model was attempted.")
