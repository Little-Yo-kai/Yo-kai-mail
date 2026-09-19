from django.conf import settings
from firecrawl import Firecrawl


class FirecrawlNotConfiguredError(RuntimeError):
    pass


def _to_json_compatible(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return value


class FirecrawlService:
    FORMATS = ["markdown", "branding", "images", "screenshot"]

    def __init__(self, client=None):
        if client is not None:
            self.client = client
            return

        api_key = settings.FIRECRAWL_API_KEY
        if not api_key:
            raise FirecrawlNotConfiguredError(
                "FIRECRAWL_API_KEY is not configured."
            )

        self.client = Firecrawl(api_key=api_key)

    def scrape(self, url: str):
        result = self.client.scrape(url, formats=self.FORMATS)
        return _to_json_compatible(result)
