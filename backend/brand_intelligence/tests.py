import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .builders import build_brand_profile
from .schemas import BrandAnalysis
from .services.gemini import GeminiBrandService


def sample_snapshot():
    return {
        "schema_version": "1.0",
        "source": {
            "requested_url": "https://example.com/product",
            "resolved_url": "https://example.com/product",
            "title": "Example Product | Example Brand",
            "description": "Premium product by Example Brand.",
            "status_code": 200,
        },
        "content": {
            "markdown": "# Example Product\nExample Brand makes premium goods.",
        },
        "visual": {
            "screenshot": "https://example.com/screenshot.png",
        },
        "assets": {
            "images": [
                "https://example.com/product.jpg",
                "https://example.com/product.jpg",
            ],
            "logo_candidate": "data:image/svg+xml;utf8,<svg></svg>",
            "favicon": "https://example.com/favicon.ico",
            "og_image": "https://example.com/og.jpg",
        },
        "detected_branding": {
            "brand_name_candidate": "Example Product",
            "color_scheme": "light",
            "colors": {
                "primary": "#000000",
                "background": "#FFFFFF",
            },
        },
    }


def sample_analysis_dict():
    return {
        "identity": {
            "name": "Example Brand",
            "description": "A premium goods brand.",
            "industry": "Retail",
        },
        "visual": {
            "color_scheme": "light",
            "colors": {
                "primary": "#000000",
                "secondary": "#F5F5F5",
                "accent": None,
                "background": "#FFFFFF",
                "text_primary": "#111111",
            },
            "typography": {
                "heading_family": "Example Sans",
                "body_family": "Example Sans",
            },
            "style_keywords": ["premium", "minimal"],
            "border_radius": "4px",
        },
        "communication": {
            "tone": ["refined", "direct"],
            "copy_characteristics": {
                "sentence_length": "short",
                "emoji_usage": "none",
                "formality": "high",
            },
        },
        "confidence": 0.91,
    }


class BrandProfileBuilderTests(APITestCase):
    def test_assets_are_bound_from_snapshot_not_model(self):
        analysis = BrandAnalysis.model_validate(sample_analysis_dict())
        profile = build_brand_profile(sample_snapshot(), analysis)

        self.assertEqual(profile.identity.name, "Example Brand")
        self.assertEqual(
            profile.assets.hero_candidates,
            [
                "https://example.com/og.jpg",
                "https://example.com/product.jpg",
            ],
        )


class GeminiBrandServiceTests(APITestCase):
    @override_settings(GEMINI_MODEL="gemini-test")
    def test_structured_output_is_validated_and_wrapped(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(sample_analysis_dict())
        )

        result = GeminiBrandService(client=client).analyze(sample_snapshot())

        self.assertEqual(result["identity"]["name"], "Example Brand")
        self.assertEqual(result["schema_version"], "1.0")
        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], "gemini-test")
        self.assertEqual(
            call["response_format"][0]["mime_type"],
            "application/json",
        )


class BrandAnalyzeViewTests(APITestCase):
    @patch("brand_intelligence.views.GeminiBrandService")
    def test_analyze_endpoint_returns_brand_profile(self, service_class):
        service_class.return_value.analyze.return_value = {
            "schema_version": "1.0",
            **sample_analysis_dict(),
            "assets": {
                "primary_logo": None,
                "hero_candidates": [],
                "og_image": None,
                "favicon": None,
            },
        }

        response = self.client.post(
            reverse("brand-analyze"),
            {"snapshot": sample_snapshot()},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["identity"]["name"],
            "Example Brand",
        )

    def test_analyze_endpoint_requires_snapshot_source(self):
        response = self.client.post(
            reverse("brand-analyze"),
            {"snapshot": {}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
