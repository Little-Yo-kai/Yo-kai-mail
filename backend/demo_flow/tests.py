import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .preview import build_preview_html
from .service import _default_campaign_brief


class DemoCampaignDefaultsTests(APITestCase):
    def test_url_only_campaign_has_safe_defaults(self):
        brief = _default_campaign_brief(
            url="https://example.com",
            brand_profile={
                "identity": {
                    "name": "Example",
                }
            },
        )

        self.assertEqual(brief["campaign_type"], "newsletter")
        self.assertEqual(brief["goal"], "brand_awareness")
        self.assertEqual(
            brief["destination_url"],
            "https://example.com",
        )
        self.assertEqual(brief["offer"]["type"], "none")
        self.assertIsNone(brief["product"])


class DemoGenerateApiTests(APITestCase):
    @patch("demo_flow.views.generate_phase1_demo")
    def test_url_only_demo_generation(self, generate_mock):
        generate_mock.return_value = {
            "mode": "automatic_reference",
            "email_design": {
                "subject": "Hello",
                "preheader": "Preview",
                "sections": [],
            },
            "render": {
                "html": "<!doctype html><html></html>",
                "preview_html": "<!doctype html><html></html>",
                "preview_asset_diagnostics": [],
                "cached_assets": [],
                "mjml": "<mjml></mjml>",
            },
        }

        response = self.client.post(
            reverse("phase1-demo-generate"),
            {
                "url": "https://example.com",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["mode"],
            "automatic_reference",
        )
        generate_mock.assert_called_once()
        self.assertIsNone(
            generate_mock.call_args.kwargs["reference_image"]
        )

    @patch("demo_flow.views.generate_phase1_demo")
    def test_uploaded_reference_is_forwarded(self, generate_mock):
        generate_mock.return_value = {
            "mode": "uploaded_reference",
            "email_design": {
                "subject": "Hello",
                "preheader": "Preview",
                "sections": [],
            },
            "render": {
                "html": "<!doctype html><html></html>",
                "preview_html": "<!doctype html><html></html>",
                "preview_asset_diagnostics": [],
                "cached_assets": [],
                "mjml": "<mjml></mjml>",
            },
        }

        image = SimpleUploadedFile(
            "reference.png",
            b"fake-image-bytes",
            content_type="image/png",
        )

        response = self.client.post(
            reverse("phase1-demo-generate"),
            {
                "url": "https://example.com",
                "reference_image": image,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["mode"],
            "uploaded_reference",
        )
        self.assertIsNotNone(
            generate_mock.call_args.kwargs["reference_image"]
        )



class DemoPreviewHtmlTests(APITestCase):
    @patch("email_assets.temp_cache._fetch_public_image")
    def test_known_email_image_is_embedded_and_cached(self, fetch_mock):
        fetch_mock.return_value = (
            b"\x89PNG\r\n\x1a\npreview-bytes",
            "image/png",
            "https://cdn.example.com/hero.png",
        )

        source_html = (
            '<html><body><img src="https://cdn.example.com/hero.png" '
            'alt="Hero"></body></html>'
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            with self.settings(EMAIL_ASSET_CACHE_DIR=cache_dir):
                preview_html, diagnostics, cached_assets = build_preview_html(
                    html_document=source_html,
                    asset_inventory=[
                        {
                            "asset_id": "hero_1",
                            "kind": "hero",
                            "url": "https://cdn.example.com/hero.png",
                            "source": "brand_profile",
                        }
                    ],
                )

        self.assertIn("data:image/png;base64,", preview_html)
        self.assertNotIn(
            'src="https://cdn.example.com/hero.png"',
            preview_html,
        )
        self.assertEqual(diagnostics[0]["status"], "embedded")
        self.assertEqual(len(cached_assets), 1)
        self.assertEqual(
            cached_assets[0]["source_url"],
            "https://cdn.example.com/hero.png",
        )
        self.assertEqual(len(cached_assets[0]["cache_key"]), 64)

    @patch("email_assets.temp_cache._fetch_public_image")
    def test_cached_preview_reuses_downloaded_bytes(self, fetch_mock):
        fetch_mock.return_value = (
            b"\x89PNG\r\n\x1a\npreview-bytes",
            "image/png",
            "https://cdn.example.com/hero.png",
        )

        source_html = (
            '<html><body><img src="https://cdn.example.com/hero.png" '
            'alt="Hero"></body></html>'
        )
        inventory = [
            {
                "asset_id": "hero_1",
                "kind": "hero",
                "url": "https://cdn.example.com/hero.png",
                "source": "brand_profile",
            }
        ]

        with tempfile.TemporaryDirectory() as cache_dir:
            with self.settings(EMAIL_ASSET_CACHE_DIR=cache_dir):
                build_preview_html(
                    html_document=source_html,
                    asset_inventory=inventory,
                )
                _, diagnostics, _ = build_preview_html(
                    html_document=source_html,
                    asset_inventory=inventory,
                )

        self.assertEqual(fetch_mock.call_count, 1)
        self.assertTrue(diagnostics[0]["cache_hit"])

    @patch("email_assets.temp_cache._fetch_public_image")
    def test_unavailable_image_keeps_original_url(self, fetch_mock):
        fetch_mock.side_effect = ValueError(
            "Image request returned HTTP 403."
        )

        source_html = (
            '<html><body><img src="https://cdn.example.com/hero.png" '
            'alt="Hero"></body></html>'
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            with self.settings(EMAIL_ASSET_CACHE_DIR=cache_dir):
                preview_html, diagnostics, cached_assets = build_preview_html(
                    html_document=source_html,
                    asset_inventory=[
                        {
                            "asset_id": "hero_1",
                            "kind": "hero",
                            "url": "https://cdn.example.com/hero.png",
                            "source": "brand_profile",
                        }
                    ],
                )

        self.assertIn(
            'src="https://cdn.example.com/hero.png"',
            preview_html,
        )
        self.assertEqual(diagnostics[0]["status"], "unavailable")
        self.assertEqual(cached_assets, [])
