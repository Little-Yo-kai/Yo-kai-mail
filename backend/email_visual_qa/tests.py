import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .schemas import DesignCritique
from .services.gemini import GeminiDesignCritic


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
            "style_keywords": ["minimal"],
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
                "headline": "A New Expression",
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
                "body": "A concise piece of final copy.",
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


def sample_reference_spec():
    return {
        "schema_version": "1.0",
        "archetype": "Luxury Editorial Product Launch",
        "summary": "Restrained image-led product launch.",
        "visual_hierarchy": {
            "hero_dominance": "very_high",
            "image_to_text_balance": "image_heavy",
            "density": "low",
            "primary_alignment": "center",
        },
        "section_sequence": [
            {
                "order": 1,
                "type": "hero",
                "purpose": "Establish aspiration.",
                "layout": "Large editorial image.",
                "alignment": "center",
                "image_usage": "dominant",
                "copy_role": "emotional hook",
            },
            {
                "order": 2,
                "type": "intro",
                "purpose": "Introduce the product story.",
                "layout": "Centered minimal copy.",
                "alignment": "center",
                "image_usage": "none",
                "copy_role": "context",
            },
            {
                "order": 3,
                "type": "cta",
                "purpose": "Invite discovery.",
                "layout": "Single understated CTA.",
                "alignment": "center",
                "image_usage": "none",
                "copy_role": "action",
            },
        ],
        "copy_formula": [
            "aspirational hook",
            "concise product context",
            "single CTA",
        ],
        "cta_style": {
            "frequency": "low",
            "placement_pattern": "After persuasion.",
            "shape": "rectangular",
            "emphasis": "medium",
        },
        "spacing_rhythm": {
            "overall": "very_generous",
            "section_separation": "strong",
        },
        "design_rules": {
            "background_strategy": "Neutral backgrounds.",
            "color_usage": "Restrained.",
            "typography_behavior": "Editorial hierarchy.",
            "image_treatment": "One dominant product image.",
            "mobile_behavior": "Stack vertically.",
        },
        "reusable_principles": [
            "Use restraint as a premium signal.",
            "Let one image dominate the composition.",
        ],
        "brand_specific_elements_to_ignore": [],
        "confidence": 1.0,
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


def sample_critique():
    return {
        "schema_version": "1.0",
        "revision_needed": True,
        "summary": (
            "The structure is restrained, but the hero needs stronger visual "
            "dominance to match the selected editorial direction."
        ),
        "strengths": [
            "The CTA cadence is appropriately low.",
            "The centered hierarchy supports the reference direction.",
        ],
        "issues": [
            {
                "category": "hierarchy",
                "severity": "major",
                "affected_section_ids": ["hero"],
                "observation": (
                    "The hero image does not dominate the first viewport enough."
                ),
                "why_it_matters": (
                    "The reference direction depends on image-first hierarchy."
                ),
                "recommended_change": (
                    "Increase hero image emphasis and reduce competing top spacing."
                ),
            }
        ],
        "priority_changes": [
            "Increase hero image dominance.",
        ],
    }


class GeminiDesignCriticTests(APITestCase):
    @override_settings(GEMINI_CRITIC_MODEL="gemini-test")
    def test_critic_uses_image_input_and_structured_output(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(sample_critique())
        )

        result = GeminiDesignCritic(client=client).critique(
            screenshot_base64="iVBORw0KGgoAAAANSUhEUg==",
            screenshot_mime_type="image/png",
            brand_profile=sample_brand_profile(),
            email_design=sample_email_design(),
            reference_design_spec=sample_reference_spec(),
            asset_inventory=sample_assets(),
            render_metadata={
                "width": 760,
                "height": 953,
                "rendered_sections": 3,
                "available_asset_ids": ["og_image"],
            },
        )

        self.assertTrue(result["revision_needed"])
        self.assertEqual(
            result["issues"][0]["affected_section_ids"],
            ["hero"],
        )

        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], "gemini-test")
        self.assertEqual(call["input"][1]["type"], "image")
        self.assertEqual(call["input"][1]["mime_type"], "image/png")
        self.assertEqual(
            call["response_format"][0]["mime_type"],
            "application/json",
        )


class DesignCritiqueApiTests(APITestCase):
    @patch("email_visual_qa.views.GeminiDesignCritic")
    @patch("email_visual_qa.views.capture_email_screenshot")
    @patch("email_visual_qa.views.compile_mjml_to_html")
    @patch("email_visual_qa.views.render_email_to_mjml")
    def test_critique_endpoint_keeps_screenshot_internal(
        self,
        render_mock,
        compile_mock,
        screenshot_mock,
        critic_class,
    ):
        render_mock.return_value = {
            "mjml": "<mjml><mj-body></mj-body></mjml>",
            "rendered_sections": 3,
            "available_asset_ids": ["og_image"],
        }
        compile_mock.return_value = {
            "html": "<!doctype html><html><body>Rendered</body></html>",
            "compiler_errors": [],
        }
        screenshot_mock.return_value = {
            "image_base64": "iVBORw0KGgoAAAANSUhEUg==",
            "mime_type": "image/png",
            "width": 760,
            "height": 953,
            "image_diagnostics": {
                "total": 1,
                "loaded": 1,
                "broken": [],
            },
        }
        critic_class.return_value.critique.return_value = sample_critique()

        response = self.client.post(
            reverse("email-design-critique"),
            {
                "brand_profile": sample_brand_profile(),
                "email_design": sample_email_design(),
                "reference_design_spec": sample_reference_spec(),
                "asset_inventory": sample_assets(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertTrue(
            response.data["data"]["design_critique"]["revision_needed"]
        )
        self.assertEqual(
            response.data["data"]["render_metadata"]["width"],
            760,
        )
        self.assertEqual(
            response.data["data"]["render_metadata"]["image_diagnostics"],
            {
                "total": 1,
                "loaded": 1,
                "broken": [],
            },
        )
        self.assertNotIn(
            "image_base64",
            response.data["data"],
        )

        critic_call = critic_class.return_value.critique.call_args.kwargs
        self.assertEqual(
            critic_call["screenshot_base64"],
            "iVBORw0KGgoAAAANSUhEUg==",
        )

    @patch("email_visual_qa.views.GeminiDesignCritic")
    @patch("email_visual_qa.views.capture_email_screenshot")
    @patch("email_visual_qa.views.compile_mjml_to_html")
    @patch("email_visual_qa.views.render_email_to_mjml")
    def test_critique_endpoint_hides_developer_diagnostics_by_default(
        self,
        render_mock,
        compile_mock,
        screenshot_mock,
        critic_class,
    ):
        render_mock.return_value = {
            "mjml": "<mjml><mj-body></mj-body></mjml>",
            "rendered_sections": 3,
            "available_asset_ids": ["og_image"],
        }
        compile_mock.return_value = {
            "html": "<!doctype html><html><body>Rendered</body></html>",
            "compiler_errors": [],
        }
        screenshot_mock.return_value = {
            "image_base64": "iVBORw0KGgoAAAANSUhEUg==",
            "mime_type": "image/png",
            "width": 760,
            "height": 953,
            "image_diagnostics": {
                "total": 1,
                "loaded": 1,
                "broken": [],
            },
            "image_network_events": [
                {"url": "https://example.com/product.jpg", "status": 200}
            ],
        }
        critic_class.return_value.critique.return_value = sample_critique()

        response = self.client.post(
            reverse("email-design-critique"),
            {
                "brand_profile": sample_brand_profile(),
                "email_design": sample_email_design(),
                "reference_design_spec": sample_reference_spec(),
                "asset_inventory": sample_assets(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(
            "developer_diagnostics",
            response.data["data"],
        )

    @patch("email_visual_qa.views.GeminiDesignCritic")
    @patch("email_visual_qa.views.capture_email_screenshot")
    @patch("email_visual_qa.views.compile_mjml_to_html")
    @patch("email_visual_qa.views.render_email_to_mjml")
    def test_critique_endpoint_can_include_developer_diagnostics(
        self,
        render_mock,
        compile_mock,
        screenshot_mock,
        critic_class,
    ):
        render_mock.return_value = {
            "mjml": "<mjml><mj-body></mj-body></mjml>",
            "rendered_sections": 3,
            "available_asset_ids": ["og_image"],
        }
        compile_mock.return_value = {
            "html": "<!doctype html><html><body>Rendered</body></html>",
            "compiler_errors": [],
        }
        screenshot_mock.return_value = {
            "image_base64": "iVBORw0KGgoAAAANSUhEUg==",
            "mime_type": "image/png",
            "width": 760,
            "height": 953,
            "image_diagnostics": {
                "total": 1,
                "loaded": 1,
                "broken": [],
            },
            "image_network_events": [
                {"url": "https://example.com/product.jpg", "status": 200}
            ],
        }
        critic_class.return_value.critique.return_value = sample_critique()

        response = self.client.post(
            reverse("email-design-critique"),
            {
                "brand_profile": sample_brand_profile(),
                "email_design": sample_email_design(),
                "reference_design_spec": sample_reference_spec(),
                "asset_inventory": sample_assets(),
                "include_diagnostics": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            "developer_diagnostics",
            response.data["data"],
        )
        self.assertIn(
            "image_network_events",
            response.data["data"]["developer_diagnostics"],
        )


class DesignCritiqueSchemaSafetyTests(APITestCase):
    def test_schema_rejects_html_css_or_mjml_markup(self):
        unsafe = sample_critique()
        unsafe["summary"] = "<style>body{display:none}</style>"

        with self.assertRaises(ValueError):
            DesignCritique.model_validate(unsafe)


class DesignRevisionApiTests(APITestCase):
    @patch("email_visual_qa.views.GeminiEmailDesignReviser")
    def test_revision_endpoint_returns_bounded_result(self, reviser_class):
        reviser_class.return_value.revise.return_value = {
            "email_design": sample_email_design(),
            "design_critique": sample_critique(),
            "revision_notes": ["Revision completed in 1 attempt(s)."],
            "attempts_used": 1,
            "max_attempts": 1,
            "terminated_reason": "approved",
            "completed": True,
        }

        response = self.client.post(
            reverse("email-design-revise"),
            {
                "brand_profile": sample_brand_profile(),
                "email_design": sample_email_design(),
                "reference_design_spec": sample_reference_spec(),
                "content_plan": {
                    "schema_version": "1.0",
                    "campaign_angle": "Angle",
                    "strategic_rationale": "Rationale",
                    "audience_focus": "Audience",
                    "primary_message": "Primary",
                    "supporting_messages": ["One"],
                    "subject_line_angles": ["One", "Two"],
                    "preheader_direction": "Direction",
                    "content_hierarchy": [
                        {
                            "order": 1,
                            "role": "emotional_hook",
                            "objective": "Objective",
                            "key_message": "Message",
                            "recommended_section_type": "hero",
                            "preferred_asset_role": "hero",
                        }
                    ],
                    "cta_strategy": {
                        "primary_action": "Discover",
                        "destination_url": "https://example.com/product",
                        "frequency": "low",
                        "placement_strategy": "After hook",
                        "tone": "clear",
                    },
                    "copy_strategy": {
                        "tone": ["refined"],
                        "density": "low",
                        "sentence_style": "Short",
                        "emphasis_style": "Restrained",
                        "avoid": [],
                    },
                    "asset_strategy": [],
                    "reference_adaptation": {
                        "principles_to_preserve": ["Restraint"],
                        "elements_to_avoid_copying": [],
                        "adaptation_notes": ["Adapt"],
                    },
                    "claim_constraints": ["No unsupported claims"],
                },
                "fact_ledger": {
                    "brand_name": "Example",
                    "product_name": "Product",
                    "verified_facts": ["Brand: Example"],
                    "offer_facts": [],
                    "authoritative_destination_url": "https://example.com/product",
                    "forbidden_claim_categories": ["unsupported claims"],
                },
                "asset_inventory": sample_assets(),
                "design_critique": sample_critique(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["attempts_used"],
            1,
        )
