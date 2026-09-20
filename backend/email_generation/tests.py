import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .builders import build_asset_inventory
from .services.gemini import GeminiCampaignStrategist


def sample_brand_profile():
    return {
        "schema_version": "1.0",
        "identity": {
            "name": "Louis Vuitton",
            "industry": "Luxury Fashion & Leather Goods",
        },
        "visual": {
            "colors": {
                "primary": "#000000",
                "secondary": "#1A1A1A",
                "accent": None,
                "background": None,
                "text_primary": "#1A1A1A",
            },
            "typography": {
                "heading_family": "Louis Vuitton Web",
                "body_family": None,
            },
        },
        "communication": {
            "tone": [
                "luxurious",
                "sophisticated",
                "refined",
                "exclusive",
            ],
        },
        "assets": {
            "primary_logo": "https://example.com/logo.svg",
            "og_image": "https://example.com/product.jpg",
            "hero_candidates": [
                "https://example.com/product.jpg",
                "https://example.com/detail.jpg",
            ],
        },
    }


def sample_campaign_brief():
    return {
        "schema_version": "1.0",
        "campaign_type": "product_launch",
        "goal": "product_discovery",
        "audience": {
            "description": "Existing luxury customers interested in handbags",
        },
        "offer": {
            "type": "none",
            "value": None,
            "code": None,
            "details": None,
        },
        "product": {
            "name": "Speedy Bandouliere 20",
            "url": "https://example.com/product",
            "description": "A compact handbag.",
        },
        "destination_url": "https://example.com/product",
        "additional_instructions": "Keep the campaign restrained.",
    }


def sample_reference_spec():
    return {
        "schema_version": "1.0",
        "archetype": "Luxury Editorial Product Launch",
        "summary": "Restrained image-led product launch.",
        "section_sequence": [
            {
                "order": 1,
                "type": "hero",
                "purpose": "Establish aspiration.",
            }
        ],
        "reusable_principles": [
            "Use restraint as a premium signal.",
        ],
        "brand_specific_elements_to_ignore": [],
    }


def sample_content_plan():
    return {
        "schema_version": "1.0",
        "campaign_angle": "An icon, considered anew",
        "strategic_rationale": (
            "Use restraint and product detail to support deliberate discovery."
        ),
        "audience_focus": "Existing luxury customers seeking a compact handbag.",
        "primary_message": "Present the product as a refined evolution.",
        "supporting_messages": [
            "Focus on form and product detail.",
            "Keep the story concise.",
        ],
        "subject_line_angles": [
            "Icon evolution",
            "Craft-focused discovery",
        ],
        "preheader_direction": "Support the subject with concise product context.",
        "content_hierarchy": [
            {
                "order": 1,
                "role": "emotional_hook",
                "objective": "Establish product desirability.",
                "key_message": "Lead with the product as the visual focus.",
                "recommended_section_type": "hero",
                "preferred_asset_role": "hero",
            },
            {
                "order": 2,
                "role": "cta",
                "objective": "Invite product discovery.",
                "key_message": "Offer one deliberate next step.",
                "recommended_section_type": "cta",
                "preferred_asset_role": "none",
            },
        ],
        "cta_strategy": {
            "primary_action": "Discover the product",
            "destination_url": "https://hallucinated.example/bad",
            "frequency": "low",
            "placement_strategy": "After the main product story.",
            "tone": "understated",
        },
        "copy_strategy": {
            "tone": ["luxurious", "refined"],
            "density": "low",
            "sentence_style": "Short editorial sentences.",
            "emphasis_style": "Use restrained, product-led emphasis.",
            "avoid": ["unsupported superlatives"],
        },
        "asset_strategy": [
            {
                "purpose": "Primary hero",
                "preferred_kind": "hero",
                "candidate_asset_ids": ["hero_1", "made_up_asset"],
                "required": True,
            }
        ],
        "reference_adaptation": {
            "principles_to_preserve": [
                "Use restraint as a premium signal.",
            ],
            "elements_to_avoid_copying": [],
            "adaptation_notes": [
                "Use the target brand's identity and product.",
            ],
        },
        "claim_constraints": [
            "Do not invent materials, prices, or availability.",
        ],
    }


class AssetInventoryTests(APITestCase):
    def test_brand_assets_are_deduplicated_and_given_stable_ids(self):
        assets = build_asset_inventory(sample_brand_profile())

        self.assertEqual(
            [asset.asset_id for asset in assets],
            ["logo_primary", "og_image", "hero_1"],
        )
        self.assertEqual(assets[-1].url, "https://example.com/detail.jpg")

    def test_explicit_asset_defaults_to_request_source(self):
        assets = build_asset_inventory(
            sample_brand_profile(),
            [
                {
                    "asset_id": "product_front",
                    "kind": "product",
                    "url": "https://example.com/front.jpg",
                }
            ],
        )

        self.assertEqual(assets[0].asset_id, "product_front")
        self.assertEqual(assets[0].source, "request")


class GeminiCampaignStrategistTests(APITestCase):
    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_plan_is_schema_validated_and_application_normalized(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(sample_content_plan())
        )

        result = GeminiCampaignStrategist(client=client).plan(
            brand_profile=sample_brand_profile(),
            campaign_brief=sample_campaign_brief(),
            reference_design_spec=sample_reference_spec(),
        )

        plan = result["content_plan"]
        self.assertEqual(
            plan["cta_strategy"]["destination_url"],
            "https://example.com/product",
        )
        self.assertEqual(
            plan["asset_strategy"][0]["candidate_asset_ids"],
            ["hero_1"],
        )

        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], "gemini-test")
        self.assertEqual(
            call["response_format"]["mime_type"],
            "application/json",
        )


class ContentPlanApiTests(APITestCase):
    @patch("email_generation.views.GeminiCampaignStrategist")
    def test_plan_endpoint_returns_content_plan(self, strategist_class):
        strategist_class.return_value.plan.return_value = {
            "content_plan": sample_content_plan(),
            "asset_inventory": [],
        }

        response = self.client.post(
            reverse("email-content-plan"),
            {
                "brand_profile": sample_brand_profile(),
                "campaign_brief": sample_campaign_brief(),
                "reference_design_spec": sample_reference_spec(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["content_plan"]["campaign_angle"],
            "An icon, considered anew",
        )
