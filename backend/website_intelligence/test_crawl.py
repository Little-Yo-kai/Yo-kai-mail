from unittest.mock import Mock, patch

from assets.services.ssrf import SSRFBlockedError
from django.test import override_settings
from rest_framework.test import APITestCase

from .services.robots import RobotsChecker


class WebsiteCrawlIntegrationTests(APITestCase):
    @override_settings(FIRECRAWL_API_KEY="test-only")
    @patch("website_intelligence.services.crawl_import.assert_safe_url")
    @patch("website_intelligence.services.crawl_import.RobotsChecker")
    @patch("website_intelligence.services.firecrawl.Firecrawl")
    def test_crawl_supports_provider_casing_and_filters_foreign_and_login_pages(
        self, provider, robots, safe_url
    ):
        robots.return_value.can_crawl.return_value = True
        provider.return_value.crawl.return_value = {
            "data": [
                {
                    "metadata": {
                        "sourceURL": "https://example.com/about",
                        "title": "About us",
                    },
                    "markdown": "Contact hello@example.com",
                },
                {
                    "metadata": {"sourceURL": "https://example.com/login"},
                    "markdown": "Login",
                },
                {
                    "metadata": {"sourceURL": "https://other.example.org/about"},
                    "markdown": "Another website",
                },
            ]
        }
        response = self.client.post(
            "/api/website/import/crawl/",
            {"url": "https://example.com", "limit": 3},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        pages = response.data["data"]["pages"]
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["source"]["page_type"], "about")
        self.assertIn("hello@example.com", pages[0]["content"]["emails"])

    @patch(
        "socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]
    )
    @patch("website_intelligence.services.crawl_import.crawl_pages")
    def test_private_destination_never_reaches_crawler(self, crawler, dns):
        response = self.client.post(
            "/api/website/import/crawl/", {"url": "http://127.0.0.1"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        crawler.assert_not_called()

    @patch(
        "assets.services.fetch.assert_safe_url",
        side_effect=[None, SSRFBlockedError("Private redirect")],
    )
    @patch("assets.services.fetch.requests.get")
    def test_robots_redirect_is_checked_before_following(self, get, safe_url):
        get.return_value = Mock(
            is_redirect=True, headers={"Location": "http://169.254.169.254/"}
        )
        with self.assertRaises(SSRFBlockedError):
            RobotsChecker("https://example.com")
        get.assert_called_once()
