from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class WebsiteImportViewTests(APITestCase):
    @patch("website_intelligence.views.FirecrawlService")
    def test_import_website_returns_firecrawl_data(self, service_class):
        service_class.return_value.scrape.return_value = {
            "markdown": "# Example",
            "images": ["https://example.com/hero.jpg"],
        }

        response = self.client.post(
            reverse("website-import"),
            {"url": "https://example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["markdown"], "# Example")
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
