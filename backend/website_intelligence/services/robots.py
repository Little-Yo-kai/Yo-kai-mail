import requests

from urllib.parse import urlparse

from urllib.robotparser import (
    RobotFileParser
)


USER_AGENT = (
    "WebsiteExtractor/1.0"
)


class RobotsChecker:

    def __init__(self, website_url):

        parsed = urlparse(
            website_url
        )

        self.robots_url = (
            f"{parsed.scheme}://"
            f"{parsed.netloc}/robots.txt"
        )

        self.parser = RobotFileParser()

        self.loaded = False

        self.load()

    def load(self):

        try:

            response = requests.get(
                self.robots_url,
                timeout=10,
                headers={
                    "User-Agent": USER_AGENT
                }
            )

            if response.status_code == 200:

                self.parser.parse(
                    response.text.splitlines()
                )

                self.loaded = True

        except requests.RequestException:

            self.loaded = False

    def can_crawl(self, url):

        # If robots.txt doesn't exist or
        # cannot be read, don't treat that
        # as an explicit disallow.
        if not self.loaded:
            return True

        return self.parser.can_fetch(
            USER_AGENT,
            url
        )

    def crawl_delay(self):

        if not self.loaded:
            return None

        return self.parser.crawl_delay(
            USER_AGENT
        )

    def sitemap_urls(self):

        if not self.loaded:
            return []

        return (
            self.parser.site_maps()
            or []
        )