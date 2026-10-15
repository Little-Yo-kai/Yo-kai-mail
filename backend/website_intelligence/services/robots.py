"""Robots policy fetched with public-host and redirect checks."""

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from assets.services.fetch import _safe_get_following_redirects

USER_AGENT = "WebsiteExtractor/1.0"
MAX_ROBOTS_BYTES = 1024 * 1024


class RobotsChecker:
    def __init__(self, website_url):
        parsed = urlparse(website_url)
        self.robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        self.parser = RobotFileParser()
        self.loaded = False
        self.load()

    def load(self):
        try:
            response = _safe_get_following_redirects(self.robots_url)
            try:
                if response.status_code == 200:
                    body = bytearray()
                    for chunk in response.iter_content(chunk_size=8192):
                        body.extend(chunk)
                        if len(body) > MAX_ROBOTS_BYTES:
                            raise ValueError("robots.txt exceeds the size limit.")
                    self.parser.parse(
                        body.decode("utf-8", errors="replace").splitlines()
                    )
                    self.loaded = True
                elif response.status_code in {401, 403}:
                    self.parser.disallow_all = True
                    self.loaded = True
            finally:
                response.close()
        except requests.RequestException:
            # A missing/unavailable robots file is not an explicit disallow.
            self.loaded = False

    def can_crawl(self, url):
        return self.parser.can_fetch(USER_AGENT, url) if self.loaded else True

    def crawl_delay(self):
        return self.parser.crawl_delay(USER_AGENT) if self.loaded else None

    def sitemap_urls(self):
        return (self.parser.site_maps() or []) if self.loaded else []
