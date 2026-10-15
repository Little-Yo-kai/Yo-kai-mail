"""Multi-page extraction using the same configured Firecrawl client as import."""

from .firecrawl import FirecrawlService, _to_json_compatible


def crawl_pages(url, limit=10):
    service = FirecrawlService()
    result = service.client.crawl(
        url,
        limit=limit,
        scrape_options={"formats": service.FORMATS},
    )
    result_dict = _to_json_compatible(result)
    pages = []
    for raw in result_dict.get("data", []):
        page = _to_json_compatible(raw)
        metadata = page.get("metadata") or {}
        page_url = (
            metadata.get("source_url")
            or metadata.get("sourceURL")
            or metadata.get("url")
            or ""
        )
        pages.append((page_url, page))
    return pages
