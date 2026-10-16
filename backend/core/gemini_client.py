"""Configure Gemini once; application fallback owns all retry decisions."""

from django.conf import settings


def gemini_json_schema(model) -> dict:
    """Keep application string limits without unsupported Gemini keywords.

    Interactions supports a JSON Schema subset and rejects some combinations
    of nested array bounds. Application limits remain enforced by Pydantic,
    while descriptions communicate them to the model.
    """

    def adapt(value):
        if isinstance(value, list):
            return [adapt(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {
            key: adapt(item)
            for key, item in value.items()
            if key not in {"maxLength", "minLength", "maxItems"}
        }
        if "maxLength" in value:
            result["description"] = (
                str(result.get("description", ""))
                + f" Maximum {value['maxLength']} characters."
            ).strip()
        if "maxItems" in value:
            result["description"] = (
                str(result.get("description", ""))
                + f" At most {value['maxItems']} items."
            ).strip()
        return result

    return adapt(model.model_json_schema())


def create_gemini_client(*, api_key, client_factory):
    client = client_factory(
        api_key=api_key,
        http_options={"timeout": int(settings.GEMINI_REQUEST_TIMEOUT_SECONDS * 1000)},
    )
    # google-genai 2.31's Interactions client has its own retry configuration.
    # HttpRetryOptions(attempts=1) still retries there, including unbounded
    # Retry-After sleeps. Disable that layer so core.ai_fallback is the only
    # retry policy. A real SDK/MockTransport regression guards this seam.
    client.interactions.sdk_configuration.retry_config = None
    return client
