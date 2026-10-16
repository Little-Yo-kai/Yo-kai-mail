from typing import ClassVar

from django.conf import settings
from firecrawl import Firecrawl

from core.generation_budget import request_timeout


class FirecrawlNotConfiguredError(RuntimeError):
    pass


def _to_json_compatible(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return value


class FirecrawlService:
    FORMATS: ClassVar = ["markdown", "branding", "images", "screenshot"]

    def __init__(self, client=None):
        if client is not None:
            self.client = client
            return

        api_key = settings.FIRECRAWL_API_KEY
        if not api_key:
            raise FirecrawlNotConfiguredError("FIRECRAWL_API_KEY is not configured.")

        self.client = Firecrawl(
            api_key=api_key,
            timeout=request_timeout(settings.FIRECRAWL_REQUEST_TIMEOUT_SECONDS),
            max_retries=1,
        )

    def scrape(self, url: str, *, max_age_ms: int | None = None):
        timeout = request_timeout(settings.FIRECRAWL_REQUEST_TIMEOUT_SECONDS)
        cache_options = {"max_age": max_age_ms} if max_age_ms is not None else {}
        result = self.client.scrape(
            url,
            formats=self.FORMATS,
            timeout=max(1, int((timeout - min(1, timeout / 10)) * 1000)),
            # SDK auto-resume may sleep for twenty minutes after a 408.
            auto_resume=False,
            **cache_options,
        )
        return _to_json_compatible(result)
