"""
Multi-page counterpart to normalizers.build_website_snapshot(). Brings
back the parts of the original scraper app that WebsiteImportView (single
page, stateless) doesn't cover: robots.txt compliance and page relevance
filtering. Stateless, same as WebsiteImportView - nothing is persisted.
"""

from urllib.parse import urlparse

from ..normalizers import build_website_snapshot
from .business_extractor import extract_emails, extract_phone_numbers
from .firecrawl_crawler import crawl_pages
from .page_relevance import is_relevant_page
from .robots import RobotsChecker

# Cheap heuristic fallback for page-type detection (guide's WI-04).
# scraper/services/ai_classifier.py already builds a real LLM
# classification prompt (build_classification_prompt) - swap this out for
# that once an actual model call is wired up. Until then this keeps
# `page_type` from just always being "other".
PATH_TYPE_HINTS = {
    "about": "about",
    "pricing": "pricing",
    "contact": "contact",
    "faq": "faq",
    "products": "product",
    "product": "product",
    "services": "service",
    "service": "service",
    "blog": "article",
    "article": "article",
    "category": "category",
}


def guess_page_type(url):

    path = urlparse(url).path.lower().strip("/")

    if path == "":
        return "home"

    for hint, page_type in PATH_TYPE_HINTS.items():

        if hint in path:
            return page_type

    return "other"


def build_website_crawl_snapshot(url: str, limit: int = 10) -> dict:
    """
    Crawl up to `limit` pages of one site, respecting robots.txt, filtering
    out obviously irrelevant paths (/login, /cart, etc.), and normalize
    each surviving page into a WebsiteSnapshot - plus a page_type guess
    and any emails/phone numbers found in its content.
    """
    print("111111111111 - ENTERED build_website_crawl_snapshot", flush=True)
    robots = RobotsChecker(url)

    if not robots.can_crawl(url):

        return {
            "website": url,
            "robots_allowed": False,
            "pages": [],
        }

    raw_pages = crawl_pages(url, limit=limit)

    print("RAW PAGES COUNT:", len(raw_pages))

    for page_url, raw in raw_pages:
        print("RAW PAGE URL:", page_url)

    snapshots = []

    for page_url, raw in raw_pages:

        if not page_url:
            print("SKIPPED: no URL")
            continue

        if not is_relevant_page(page_url):
            print("SKIPPED: irrelevant:", page_url)
            continue

        if not robots.can_crawl(page_url):
            print("SKIPPED: robots:", page_url)
            continue

        print("ACCEPTED:", page_url)

        snapshot = build_website_snapshot(page_url, raw)

        markdown = snapshot["content"]["markdown"]

        snapshot["content"]["emails"] = extract_emails(markdown)
        snapshot["content"]["phone_numbers"] = extract_phone_numbers(markdown)
        snapshot["source"]["page_type"] = guess_page_type(page_url)

        snapshots.append(snapshot)

    print("FINAL SNAPSHOTS COUNT:", len(snapshots))

    return {
    "website": url,
    "robots_allowed": True,
    "pages": snapshots,
}