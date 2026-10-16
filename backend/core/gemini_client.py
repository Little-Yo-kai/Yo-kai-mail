"""Configure Gemini once; application fallback owns all retry decisions."""

from django.conf import settings


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
