from django.conf import settings
from firecrawl import Firecrawl


def crawl_website(url, limit=10):
    
    app = Firecrawl(
        api_key=settings.FIRECRAWL_API_KEY
    )

    result = app.crawl(
        url,
        limit=limit,
        scrape_options={
            "formats": ["markdown", "html"]
        }
    )

    result_dict = dict(result)

    pages = []

    for page in result_dict.get("data", []):

        page_dict = dict(page)

        metadata = dict(
            page_dict.get("metadata", [])
        )

        page_url = (
            metadata.get("source_url")
            or metadata.get("sourceURL")
            or metadata.get("url")
            or ""
        )

        status_code = (
            metadata.get("status_code")
            or metadata.get("statusCode")
        )

        pages.append({
            "url": page_url,
            "title": metadata.get("title") or "",
            "description": metadata.get("description") or "",
            "content": page_dict.get("markdown") or "",
            "html": page_dict.get("html") or "",
            "status_code": status_code,
        })

    return pages
 
def crawl_pages(url, limit=10):
    from .firecrawl import _to_json_compatible
 
    app = Firecrawl(
        api_key=settings.FIRECRAWL_API_KEY
    )

 
    result = app.crawl(
        url,
        limit=limit,
        scrape_options={
            "formats": ["markdown", "branding", "images", "screenshot"]
        },
    )

    result_dict = _to_json_compatible(result)
 
    pages = []
 
    for page in result_dict.get("data", []):
 
        page = _to_json_compatible(page)
 
        metadata = page.get("metadata") or {}
 
        page_url = (
            metadata.get("source_url")
            or metadata.get("url")
            or ""
        )
        pages.append((page_url, page))
    return pages