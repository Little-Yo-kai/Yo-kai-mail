import json
from types import SimpleNamespace
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .compiler import compile_mjml_to_html
from .renderer import render_email_to_mjml


def sample_brand_profile():
    return {
        "schema_version": "1.0",
        "identity": {
            "name": "Example",
            "description": "Example brand",
            "industry": "Fashion",
        },
        "visual": {
            "color_scheme": "light",
            "colors": {
                "primary": "#111111",
                "secondary": "#777777",
                "accent": None,
                "background": "#FFFFFF",
                "text_primary": "#111111",
            },
            "typography": {
                "heading_family": "Arial",
                "body_family": "Arial",
            },
            "style_keywords": [],
            "border_radius": None,
        },
        "communication": {
            "tone": ["refined"],
            "copy_characteristics": {
                "sentence_length": "short",
                "emoji_usage": "none",
                "formality": "high",
            },
        },
        "assets": {
            "primary_logo": None,
            "hero_candidates": [],
            "og_image": "https://example.com/product.jpg",
            "favicon": None,
        },
        "confidence": 0.9,
    }


def sample_email_design():
    return {
        "schema_version": "1.0",
        "subject": "A considered introduction",
        "preheader": "Discover the collection.",
        "theme": {
            "content_width": "standard",
            "heading_font_role": "brand_heading",
            "body_font_role": "brand_body",
            "primary_color_role": "primary",
            "background_color_role": "background",
            "button_color_role": "primary",
        },
        "sections": [
            {
                "id": "hero",
                "order": 1,
                "type": "hero",
                "layout": "full_width",
                "eyebrow": "EXAMPLE",
                "headline": "A <script>alert(1)</script> New Expression",
                "body": None,
                "asset_ids": ["og_image"],
                "items": [],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "generous",
                    "background_role": "transparent",
                },
            },
            {
                "id": "intro",
                "order": 2,
                "type": "intro",
                "layout": "centered",
                "eyebrow": None,
                "headline": "The Story",
                "body": "A concise piece of final recipient-facing copy.",
                "asset_ids": [],
                "items": [],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "balanced",
                    "background_role": "transparent",
                },
            },
            {
                "id": "cta",
                "order": 3,
                "type": "cta",
                "layout": "centered",
                "eyebrow": None,
                "headline": None,
                "body": None,
                "asset_ids": [],
                "items": [],
                "cta": {
                    "label": "Discover",
                    "url": "https://example.com/product",
                },
                "style": {
                    "alignment": "center",
                    "spacing": "generous",
                    "background_role": "transparent",
                },
            },
        ],
    }


def sample_assets():
    return [
        {
            "asset_id": "og_image",
            "kind": "og",
            "url": "https://example.com/product.jpg",
            "source": "brand_profile",
        }
    ]


class DeterministicMJMLRendererTests(APITestCase):
    def test_renderer_resolves_assets_and_escapes_copy(self):
        result = render_email_to_mjml(
            brand_profile=sample_brand_profile(),
            email_design=sample_email_design(),
            asset_inventory=sample_assets(),
        )

        mjml = result["mjml"]

        self.assertIn("<mjml>", mjml)
        self.assertIn(
            'src="https://example.com/product.jpg"',
            mjml,
        )
        self.assertIn(
            "A &lt;script&gt;alert(1)&lt;/script&gt; New Expression",
            mjml,
        )
        self.assertNotIn("<script>", mjml)
        self.assertIn(
            'href="https://example.com/product"',
            mjml,
        )
        self.assertEqual(result["rendered_sections"], 3)

    def test_renderer_drops_non_http_asset_urls(self):
        assets = sample_assets()
        assets[0]["url"] = "data:image/svg+xml;base64,unsafe"

        result = render_email_to_mjml(
            brand_profile=sample_brand_profile(),
            email_design=sample_email_design(),
            asset_inventory=assets,
        )

        self.assertNotIn("data:image", result["mjml"])
        self.assertEqual(result["available_asset_ids"], [])

    def test_renderer_drops_unsafe_cta_urls(self):
        design = sample_email_design()
        design["sections"][2]["cta"]["url"] = "javascript:alert(1)"

        result = render_email_to_mjml(
            brand_profile=sample_brand_profile(),
            email_design=design,
            asset_inventory=sample_assets(),
        )

        self.assertNotIn("javascript:", result["mjml"])
        self.assertNotIn("<mj-button", result["mjml"])


class MJMLRenderApiTests(APITestCase):
    def test_mjml_endpoint_returns_deterministic_output(self):
        response = self.client.post(
            reverse("email-render-mjml"),
            {
                "brand_profile": sample_brand_profile(),
                "email_design": sample_email_design(),
                "asset_inventory": sample_assets(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn(
            "<mjml>",
            response.data["data"]["mjml"],
        )
        self.assertEqual(
            response.data["data"]["resolved_theme"]["content_width"],
            "600px",
        )



class MJMLCompilerBridgeTests(APITestCase):
    @patch("email_rendering.compiler.subprocess.run")
    def test_compiler_returns_html_and_errors(self, run_mock):
        run_mock.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "html": "<!doctype html><html><body>Hello</body></html>",
                    "errors": [],
                }
            ),
            stderr="",
        )

        result = compile_mjml_to_html(
            "<mjml><mj-body></mj-body></mjml>"
        )

        self.assertIn("<!doctype html>", result["html"])
        self.assertEqual(result["compiler_errors"], [])

        call = run_mock.call_args
        self.assertIn("compile.mjs", call.args[0][1])
        self.assertEqual(
            call.kwargs["input"],
            "<mjml><mj-body></mj-body></mjml>",
        )
        self.assertEqual(call.kwargs["encoding"], "utf-8")
        self.assertEqual(call.kwargs["errors"], "strict")


class HTMLRenderApiTests(APITestCase):
    @patch("email_rendering.views.compile_mjml_to_html")
    def test_html_endpoint_renders_then_compiles(self, compile_mock):
        compile_mock.return_value = {
            "html": "<!doctype html><html><body>Rendered</body></html>",
            "compiler_errors": [],
        }

        response = self.client.post(
            reverse("email-render-html"),
            {
                "brand_profile": sample_brand_profile(),
                "email_design": sample_email_design(),
                "asset_inventory": sample_assets(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn(
            "<!doctype html>",
            response.data["data"]["html"],
        )
        self.assertIn(
            "<mjml>",
            response.data["data"]["mjml"],
        )
        self.assertEqual(
            response.data["data"]["compiler_errors"],
            [],
        )
        compile_mock.assert_called_once()



class EmailScreenshotApiTests(APITestCase):
    @patch("email_rendering.views.capture_email_screenshot")
    @patch("email_rendering.views.compile_mjml_to_html")
    def test_screenshot_endpoint_renders_compiles_and_captures(
        self,
        compile_mock,
        capture_mock,
    ):
        compile_mock.return_value = {
            "html": "<!doctype html><html><body>Rendered</body></html>",
            "compiler_errors": [],
        }
        capture_mock.return_value = {
            "image_base64": "iVBORw0KGgoAAAANSUhEUg==",
            "mime_type": "image/png",
            "width": 760,
            "height": 1400,
        }

        response = self.client.post(
            reverse("email-render-screenshot"),
            {
                "brand_profile": sample_brand_profile(),
                "email_design": sample_email_design(),
                "asset_inventory": sample_assets(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["screenshot"]["mime_type"],
            "image/png",
        )
        self.assertEqual(
            response.data["data"]["screenshot"]["width"],
            760,
        )
        self.assertEqual(
            response.data["data"]["compiler_errors"],
            [],
        )

        capture_mock.assert_called_once()
        call = capture_mock.call_args
        self.assertIn("<!doctype html>", call.args[0])
        self.assertEqual(
            call.kwargs["asset_urls"],
            ["https://example.com/product.jpg"],
        )
