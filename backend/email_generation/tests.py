import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import override_settings
from django.urls import reverse
from pydantic import ValidationError
from rest_framework import status
from rest_framework.test import APITestCase

from .builders import build_asset_inventory, build_fact_ledger
from .schemas import EmailDesign
from .services.composer import GeminiEmailDesignComposer
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
            "copy_characteristics": {
                "sentence_length": "medium",
                "emoji_usage": "none",
                "formality": "high",
            },
        },
        "assets": {
            "primary_logo": "https://example.com/logo.svg",
            "og_image": "https://example.com/product.jpg",
            "hero_candidates": [
                "https://example.com/product.jpg",
                "https://example.com/detail.jpg",
            ],
        },
        "confidence": 0.95,
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
                "copy_role": "emotional_hook",
            }
        ],
        "copy_formula": ["aspirational_hook"],
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
            "background_strategy": "Neutral.",
            "color_usage": "Restrained.",
            "typography_behavior": "Editorial.",
            "image_treatment": "Image-led.",
            "mobile_behavior": "Stack.",
        },
        "reusable_principles": [
            "Use restraint as a premium signal.",
        ],
        "brand_specific_elements_to_ignore": [],
        "confidence": 1.0,
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
    def test_source_photo_renditions_do_not_become_repeated_images(self):
        profile = sample_brand_profile()
        profile["assets"] = {
            "primary_logo": "data:image/svg+xml,<svg/>",
            "og_image": "https://example.com/is/image/shop/1/PP_VP_L/product.jpg?wid=1200",
            "hero_candidates": ["https://example.com/is/image/shop/1/PP_VP_M/product.jpg?wid=750"],
        }
        assets = build_asset_inventory(profile)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].asset_id, "og_image")
        self.assertIn("PP_VP_M", assets[0].url)

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



def sample_fact_ledger():
    return build_fact_ledger(
        sample_brand_profile(),
        sample_campaign_brief(),
    ).model_dump(mode="json")


def sample_email_design():
    return {
        "schema_version": "1.0",
        "subject": "An icon, considered anew",
        "preheader": "Discover the Speedy Bandouliere 20.",
        "theme": {
            "content_width": "standard",
            "heading_font_role": "brand_heading",
            "body_font_role": "brand_body",
            "primary_color_role": "text_primary",
            "background_color_role": "background",
            "button_color_role": "text_primary",
        },
        "sections": [
            {
                "id": "hero",
                "order": 1,
                "type": "hero",
                "layout": "full_width",
                "eyebrow": "Speedy Bandouliere 20",
                "headline": "An Icon, Reimagined",
                "body": "A compact expression in Monogram Empreinte leather.",
                "asset_ids": ["og_image", "invented_asset"],
                "items": [],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "very_generous",
                    "background_role": "brand_background",
                },
            },
            {
                "id": "hero",
                "order": 4,
                "type": "cta",
                "layout": "minimal",
                "eyebrow": None,
                "headline": None,
                "body": None,
                "asset_ids": [],
                "items": [],
                "cta": {
                    "label": "Discover the Creation",
                    "url": "https://hallucinated.example",
                },
                "style": {
                    "alignment": "center",
                    "spacing": "generous",
                    "background_role": "transparent",
                },
            },
        ],
    }


class FactLedgerTests(APITestCase):
    def test_fact_ledger_is_built_only_from_validated_inputs(self):
        ledger = build_fact_ledger(
            sample_brand_profile(),
            sample_campaign_brief(),
        )

        self.assertEqual(ledger.brand_name, "Louis Vuitton")
        self.assertEqual(
            ledger.authoritative_destination_url,
            "https://example.com/product",
        )
        self.assertTrue(
            any(
                "A compact handbag." in fact
                for fact in ledger.verified_facts
            )
        )


class GeminiEmailDesignComposerTests(APITestCase):
    def test_bare_feature_labels_use_approved_product_story_without_an_ai_retry(self):
        plan = sample_content_plan()
        approved_copy = "A compact handbag with a removable pouch."
        plan["content_hierarchy"].append({
            "order": 3, "role": "product_feature", "objective": "Explain the product",
            "key_message": approved_copy, "recommended_section_type": "product_feature",
            "preferred_asset_role": "none",
        })
        design = sample_email_design()
        feature = dict(design["sections"][0])
        feature.update({"id": "feature", "type": "product_feature", "order": 2,
                        "body": None, "asset_ids": [], "items": [{"title": "Vague label"}]})
        design["sections"].insert(1, feature)
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(output_text=json.dumps(design))
        result = GeminiEmailDesignComposer(client=client).compose(
            brand_profile=sample_brand_profile(), reference_design_spec=sample_reference_spec(),
            content_plan=plan,
            asset_inventory=[asset.model_dump(mode="json") for asset in build_asset_inventory(sample_brand_profile())],
            fact_ledger=sample_fact_ledger(),
        )
        section = next(section for section in result["email_design"]["sections"] if section["id"] == "feature")
        self.assertEqual(section["body"], approved_copy)
        self.assertEqual(section["items"], [])
        self.assertEqual(client.interactions.create.call_count, 1)

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_runaway_feature_copy_is_repaired_and_repeated_photos_are_removed(self):
        invalid = sample_email_design()
        invalid["sections"][0]["headline"] = "Repeated claim " * 1000
        repaired = sample_email_design()
        repaired["sections"][1]["asset_ids"] = ["og_image"]
        client = Mock()
        client.interactions.create.side_effect = [
            SimpleNamespace(output_text=json.dumps(invalid)),
            SimpleNamespace(output_text=json.dumps(repaired)),
        ]
        result = GeminiEmailDesignComposer(client=client).compose(
            brand_profile=sample_brand_profile(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(),
            asset_inventory=[asset.model_dump(mode="json") for asset in build_asset_inventory(sample_brand_profile())],
            fact_ledger=sample_fact_ledger(),
        )
        self.assertEqual(client.interactions.create.call_count, 2)
        provider_schema = client.interactions.create.call_args.kwargs["response_format"]["schema"]
        self.assertNotIn("maxLength", json.dumps(provider_schema))
        self.assertIn("Maximum 160 characters", json.dumps(provider_schema))
        self.assertEqual(result["email_design"]["sections"][1]["asset_ids"], [])
        self.assertLessEqual(len(result["email_design"]["sections"][0]["headline"]), 160)

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_design_is_schema_validated_and_application_normalized(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(sample_email_design())
        )

        composer = GeminiEmailDesignComposer(client=client)
        result = composer.compose(
            brand_profile=sample_brand_profile(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(),
            asset_inventory=[
                asset.model_dump(mode="json")
                for asset in build_asset_inventory(sample_brand_profile())
            ],
            fact_ledger=sample_fact_ledger(),
        )

        design = result["email_design"]
        self.assertEqual(design["sections"][0]["asset_ids"], ["og_image"])
        self.assertEqual(design["sections"][0]["order"], 1)
        self.assertEqual(design["sections"][1]["order"], 2)
        self.assertNotEqual(
            design["sections"][0]["id"],
            design["sections"][1]["id"],
        )
        self.assertEqual(
            design["sections"][1]["cta"]["url"],
            "https://example.com/product",
        )

        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], "gemini-test")
        self.assertEqual(
            call["response_format"]["mime_type"],
            "application/json",
        )



    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_safe_structural_omissions_are_recovered_without_ai_retry(self):
        invalid_design = sample_email_design()
        invalid_design["sections"].insert(
            1,
            {
                "id": "intro",
                "order": 2,
                "type": "intro",
                "layout": "centered",
                "eyebrow": "INTRO",
                "headline": "The Story",
                "body": None,
                "asset_ids": [],
                "items": [],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "balanced",
                    "background_role": "transparent",
                },
            },
        )
        invalid_design["sections"][2]["cta"] = None

        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(invalid_design)
        )

        composer = GeminiEmailDesignComposer(client=client)
        result = composer.compose(
            brand_profile=sample_brand_profile(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(),
            asset_inventory=[
                asset.model_dump(mode="json")
                for asset in build_asset_inventory(
                    sample_brand_profile()
                )
            ],
            fact_ledger=sample_fact_ledger(),
        )

        self.assertEqual(client.interactions.create.call_count, 1)
        self.assertTrue(result["email_design"]["sections"][1]["body"])
        self.assertIsNotNone(
            result["email_design"]["sections"][2]["cta"]
        )
        self.assertEqual(
            result["email_design"]["sections"][2]["cta"]["url"],
            "https://example.com/product",
        )
        self.assertGreaterEqual(len(result["recovery_actions"]), 2)

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_version_is_updated_for_populated_variant_fields(self):
        design = sample_email_design()
        design["schema_version"] = "1.0"
        design["alternative_subjects"] = ["A different subject"]

        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(design)
        )

        result = GeminiEmailDesignComposer(client=client).compose(
            brand_profile=sample_brand_profile(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(),
            asset_inventory=[
                asset.model_dump(mode="json")
                for asset in build_asset_inventory(
                    sample_brand_profile()
                )
            ],
            fact_ledger=sample_fact_ledger(),
        )

        self.assertEqual(client.interactions.create.call_count, 1)
        self.assertEqual(
            result["email_design"]["schema_version"],
            "1.1",
        )
        self.assertTrue(
            any(
                "schema_version to 1.1" in action
                for action in result["recovery_actions"]
            )
        )

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_unrecoverable_design_gets_one_bounded_repair_attempt(self):
        invalid_design = sample_email_design()
        invalid_design["sections"].insert(
            1,
            {
                "id": "grid",
                "order": 2,
                "type": "product_grid",
                "layout": "grid_2",
                "eyebrow": "PRODUCTS",
                "headline": "Explore",
                "body": None,
                "asset_ids": [],
                "items": [],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "balanced",
                    "background_role": "transparent",
                },
            },
        )

        client = Mock()
        client.interactions.create.side_effect = [
            SimpleNamespace(
                output_text=json.dumps(invalid_design)
            ),
            SimpleNamespace(
                output_text=json.dumps(sample_email_design())
            ),
        ]

        composer = GeminiEmailDesignComposer(client=client)
        result = composer.compose(
            brand_profile=sample_brand_profile(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(),
            asset_inventory=[
                asset.model_dump(mode="json")
                for asset in build_asset_inventory(
                    sample_brand_profile()
                )
            ],
            fact_ledger=sample_fact_ledger(),
        )

        self.assertEqual(
            client.interactions.create.call_count,
            2,
        )
        second_prompt = (
            client.interactions.create.call_args_list[1]
            .kwargs["input"]
        )
        self.assertIn("REPAIR TASK", second_prompt)
        self.assertIn(
            "APPLICATION VALIDATION ERRORS",
            second_prompt,
        )
        self.assertEqual(
            result["email_design"]["subject"],
            sample_email_design()["subject"],
        )


class EmailDesignApiTests(APITestCase):
    @patch("email_generation.views.GeminiEmailDesignComposer")
    def test_design_endpoint_returns_email_design(self, composer_class):
        composer_class.return_value.compose.return_value = {
            "email_design": sample_email_design(),
            "asset_inventory": [],
        }

        response = self.client.post(
            reverse("email-design"),
            {
                "brand_profile": sample_brand_profile(),
                "reference_design_spec": sample_reference_spec(),
                "content_plan": sample_content_plan(),
                "asset_inventory": [],
                "fact_ledger": sample_fact_ledger(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["email_design"]["subject"],
            "An icon, considered anew",
        )



class EmailDesignSchemaTests(APITestCase):
    def test_intro_section_cannot_silently_omit_final_body_copy(self):
        design = sample_email_design()
        design["sections"].insert(
            1,
            {
                "id": "intro",
                "order": 2,
                "type": "intro",
                "layout": "centered",
                "eyebrow": "SEASONAL LEATHER GOODS",
                "headline": "Monogram Empreinte Gradient",
                "body": None,
                "asset_ids": [],
                "items": [],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "generous",
                    "background_role": "transparent",
                },
            },
        )

        with self.assertRaises(ValidationError):
            EmailDesign.model_validate(design)


    def test_product_feature_accepts_meaningful_items_without_body(self):
        design = sample_email_design()
        design["sections"].insert(
            1,
            {
                "id": "details",
                "order": 2,
                "type": "product_feature",
                "layout": "stacked",
                "eyebrow": "FEATURES",
                "headline": "Creative Focus",
                "body": None,
                "asset_ids": [],
                "items": [
                    {
                        "title": "High-performance energy",
                        "body": None,
                        "asset_id": None,
                        "cta": None,
                    }
                ],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "balanced",
                    "background_role": "transparent",
                },
            },
        )

        validated = EmailDesign.model_validate(design)
        self.assertEqual(
            validated.sections[1].items[0].title,
            "High-performance energy",
        )

    def test_narrative_sections_accept_meaningful_items_without_body(self):
        for section_type in (
            "intro",
            "product_feature",
            "lifestyle",
            "offer",
        ):
            with self.subTest(section_type=section_type):
                design = sample_email_design()
                design["sections"].insert(
                    1,
                    {
                        "id": f"{section_type}_items",
                        "order": 2,
                        "type": section_type,
                        "layout": "stacked",
                        "eyebrow": "DETAIL",
                        "headline": "A focused story",
                        "body": None,
                        "asset_ids": [],
                        "items": [
                            {
                                "title": "A Modern Environment",
                                "body": (
                                    "Meaningful finished recipient-facing copy."
                                ),
                                "asset_id": None,
                                "cta": None,
                            }
                        ],
                        "cta": None,
                        "style": {
                            "alignment": "center",
                            "spacing": "balanced",
                            "background_role": "transparent",
                        },
                    },
                )

                validated = EmailDesign.model_validate(design)
                self.assertEqual(
                    validated.sections[1].items[0].title,
                    "A Modern Environment",
                )

    def test_product_feature_accepts_concise_finished_body_copy(self):
        design = sample_email_design()
        design["sections"].insert(
            1,
            {
                "id": "details",
                "order": 2,
                "type": "product_feature",
                "layout": "centered",
                "eyebrow": "DESIGN DETAILS",
                "headline": "Signature Accents",
                "body": (
                    "Silver-toned hardware, a signature padlock, and a "
                    "removable adjustable strap complete the compact design."
                ),
                "asset_ids": [],
                "items": [],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "balanced",
                    "background_role": "transparent",
                },
            },
        )

        validated = EmailDesign.model_validate(design)
        self.assertEqual(
            validated.sections[1].body,
            (
                "Silver-toned hardware, a signature padlock, and a "
                "removable adjustable strap complete the compact design."
            ),
        )
