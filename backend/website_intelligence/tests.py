from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .normalizers import build_website_snapshot


class WebsiteSnapshotNormalizerTests(APITestCase):
    def test_builds_provider_independent_snapshot(self):
        raw = {
            "markdown": "# Side Trunk MM",
            "metadata": {
                "title": "Side Trunk MM | LOUIS VUITTON",
                "description": "Product description",
                "source_url": "https://example.com/product",
                "language": "en",
                "status_code": 200,
                "favicon": "https://example.com/favicon.ico",
                "scrape_id": "scrape_123",
                "credits_used": 1,
                "proxy_used": "basic",
            },
            "images": [
                "https://example.com/hero.jpg",
                "data:image/gif;base64,AAAA",
            ],
            "screenshot": "https://example.com/screenshot.png",
            "branding": {
                "brand_name": "Side Trunk MM",
                "color_scheme": "light",
                "logo": "data:image/svg+xml;utf8,<svg></svg>",
                "colors": {
                    "primary": "#000000",
                    "background": "#FFFFFF",
                },
                "fonts": [
                    {"family": "Example Sans", "role": "body"},
                ],
                "typography": {
                    "fontFamilies": {"primary": "Example Sans"},
                },
                "spacing": {"baseUnit": 4},
                "components": {
                    "buttonPrimary": {"borderRadius": "40px"},
                },
                "personality": {"tone": "professional"},
                "confidence": {"overall": 0.9},
                "images": {
                    "favicon": "https://example.com/brand-favicon.ico",
                    "ogImage": "https://example.com/og.jpg",
                },
            },
        }

        snapshot = build_website_snapshot(
            "https://example.com/product",
            raw,
        )

        self.assertEqual(snapshot["schema_version"], "1.0")
        self.assertEqual(
            snapshot["source"]["title"],
            "Side Trunk MM | LOUIS VUITTON",
        )
        self.assertEqual(
            snapshot["detected_branding"]["brand_name_candidate"],
            "Side Trunk MM",
        )
        self.assertEqual(
            snapshot["assets"]["images"],
            ["https://example.com/hero.jpg"],
        )
        self.assertEqual(
            snapshot["assets"]["og_image"],
            "https://example.com/og.jpg",
        )
        self.assertEqual(
            snapshot["extraction"]["provider"],
            "firecrawl",
        )


class WebsiteImportViewTests(APITestCase):
    @patch("website_intelligence.views.FirecrawlService")
    def test_import_website_returns_website_snapshot(self, service_class):
        service_class.return_value.scrape.return_value = {
            "markdown": "# Example",
            "metadata": {
                "title": "Example",
                "source_url": "https://example.com/",
                "status_code": 200,
            },
            "images": ["https://example.com/hero.jpg"],
            "branding": {
                "brand_name": "Example",
                "colors": {"primary": "#111111"},
            },
        }

        response = self.client.post(
            reverse("website-import"),
            {"url": "https://example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["schema_version"], "1.0")
        self.assertEqual(
            response.data["data"]["source"]["title"],
            "Example",
        )
        self.assertEqual(
            response.data["data"]["detected_branding"][
                "brand_name_candidate"
            ],
            "Example",
        )
        service_class.return_value.scrape.assert_called_once_with(
            "https://example.com"
        )

    def test_import_website_requires_url(self):
        response = self.client.post(
            reverse("website-import"),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_import_website_rejects_invalid_url(self):
        response = self.client.post(
            reverse("website-import"),
            {"url": "not-a-url"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
