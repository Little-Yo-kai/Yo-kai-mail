import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .services.gemini import GeminiReferenceDesignService


def sample_spec():
    return {
        "schema_version": "1.0",
        "archetype": "editorial_product_launch",
        "summary": "Image-led editorial launch with repeated conversion moments.",
        "visual_hierarchy": {
            "hero_dominance": "very_high",
            "image_to_text_balance": "image_heavy",
            "density": "medium",
            "primary_alignment": "center",
        },
        "section_sequence": [
            {
                "order": 1,
                "type": "hero",
                "purpose": "Create an emotional product-first hook.",
                "layout": "Full-width image with concise headline.",
                "alignment": "center",
                "image_usage": "dominant",
                "copy_role": "emotional_hook",
            },
            {
                "order": 2,
                "type": "intro",
                "purpose": "Introduce the campaign context.",
                "layout": "Narrow centered text block.",
                "alignment": "center",
                "image_usage": "none",
                "copy_role": "campaign_context",
            },
        ],
        "copy_formula": [
            "emotional_hook",
            "campaign_context",
            "product_introduction",
            "cta",
        ],
        "cta_style": {
            "frequency": "medium",
            "placement_pattern": "After major persuasion sections.",
            "shape": "rectangular",
            "emphasis": "strong",
        },
        "spacing_rhythm": {
            "overall": "generous",
            "section_separation": "strong",
        },
        "design_rules": {
            "background_strategy": "Mostly clean neutral surfaces.",
            "color_usage": "High contrast accents reserved for emphasis.",
            "typography_behavior": "Large display headlines with restrained body text.",
            "image_treatment": "Large editorial imagery drives the composition.",
            "mobile_behavior": "Stack columns and retain dominant imagery.",
        },
        "reusable_principles": [
            "Lead with one dominant visual.",
            "Alternate visual and copy-heavy sections.",
        ],
        "brand_specific_elements_to_ignore": [
            "Original logo",
            "Original product names",
            "Original brand colors",
        ],
        "confidence": 0.94,
    }


def sample_image():
    return SimpleUploadedFile(
        "reference.png",
        b"fake-image-bytes",
        content_type="image/png",
    )


class GeminiReferenceDesignServiceTests(APITestCase):
    @override_settings(GEMINI_MODEL="gemini-test")
    def test_image_and_schema_are_sent_to_gemini(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(sample_spec())
        )

        result = GeminiReferenceDesignService(client=client).analyze(
            sample_image()
        )

        self.assertEqual(result["archetype"], "editorial_product_launch")

        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], "gemini-test")
        self.assertEqual(call["input"][1]["type"], "image")
        self.assertEqual(call["input"][1]["mime_type"], "image/png")
        self.assertEqual(
            call["response_format"][0]["mime_type"],
            "application/json",
        )


class ReferenceDesignAnalyzeViewTests(APITestCase):
    @patch("reference_design.views.GeminiReferenceDesignService")
    def test_analyze_endpoint_returns_reference_design_spec(
        self,
        service_class,
    ):
        service_class.return_value.analyze.return_value = sample_spec()

        response = self.client.post(
            reverse("reference-design-analyze"),
            {"image": sample_image()},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["archetype"],
            "editorial_product_launch",
        )

    def test_rejects_unsupported_file_type(self):
        bad_file = SimpleUploadedFile(
            "reference.txt",
            b"not-an-image",
            content_type="text/plain",
        )

        response = self.client.post(
            reverse("reference-design-analyze"),
            {"image": bad_file},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
