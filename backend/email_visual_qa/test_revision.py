import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from brand_intelligence.schemas import BrandProfile
from email_generation.schemas import AssetDescriptor, EmailDesign
from reference_design.schemas import ReferenceDesignSpec

from .schemas import DesignCritique
from .services.gemini import DesignCritiqueError
from .services.revision import GeminiEmailDesignReviser


def sample_brand_profile(name: str = "Example"):
    return {
        "schema_version": "1.0",
        "identity": {
            "name": name,
            "description": f"{name} brand",
            "industry": "Retail",
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


def sample_reference_spec():
    return {
        "schema_version": "1.0",
        "archetype": "Editorial",
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
                "layout": "Large image.",
                "alignment": "center",
                "image_usage": "dominant",
                "copy_role": "emotional hook",
            },
            {
                "order": 2,
                "type": "cta",
                "purpose": "Action.",
                "layout": "Single CTA.",
                "alignment": "center",
                "image_usage": "none",
                "copy_role": "action",
            },
        ],
        "copy_formula": ["hook", "cta"],
        "cta_style": {
            "frequency": "low",
            "placement_pattern": "After persuasion.",
            "shape": "rectangular",
            "emphasis": "medium",
        },
        "spacing_rhythm": {
            "overall": "generous",
            "section_separation": "strong",
        },
        "design_rules": {
            "background_strategy": "Neutral.",
            "color_usage": "Restrained.",
            "typography_behavior": "Editorial.",
            "image_treatment": "Dominant hero.",
            "mobile_behavior": "Stack.",
        },
        "reusable_principles": ["Use restraint as a premium signal."],
        "brand_specific_elements_to_ignore": [],
        "confidence": 0.95,
    }


def sample_content_plan(primary_action: str, destination_url: str):
    return {
        "schema_version": "1.0",
        "campaign_angle": "Focused launch",
        "strategic_rationale": "Lead with one strong visual and one CTA.",
        "audience_focus": "Prospects.",
        "primary_message": "A concise product story.",
        "supporting_messages": ["Use a clear hero.", "Keep CTA focused."],
        "subject_line_angles": ["New drop", "A concise reveal"],
        "preheader_direction": "Use concise supporting context.",
        "content_hierarchy": [
            {
                "order": 1,
                "role": "emotional_hook",
                "objective": "Lead with a visual.",
                "key_message": "A concise product story.",
                "recommended_section_type": "hero",
                "preferred_asset_role": "hero",
            },
            {
                "order": 2,
                "role": "cta",
                "objective": "Drive action.",
                "key_message": "Give one next step.",
                "recommended_section_type": "cta",
                "preferred_asset_role": "none",
            },
        ],
        "cta_strategy": {
            "primary_action": primary_action,
            "destination_url": destination_url,
            "frequency": "low",
            "placement_strategy": "After persuasion.",
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
            "principles_to_preserve": ["Use restraint as a premium signal."],
            "elements_to_avoid_copying": [],
            "adaptation_notes": ["Adapt to brand assets."],
        },
        "claim_constraints": ["Do not invent claims."],
    }


def sample_fact_ledger(brand_name: str, destination_url: str):
    return {
        "brand_name": brand_name,
        "product_name": "Product",
        "verified_facts": [f"Brand: {brand_name}"],
        "offer_facts": [],
        "authoritative_destination_url": destination_url,
        "forbidden_claim_categories": ["unsupported claims"],
    }


def sample_assets(allowed_asset_ids: list[str]):
    by_id = {
        "hero_1": {
            "asset_id": "hero_1",
            "kind": "hero",
            "url": "https://example.com/hero.jpg",
            "source": "brand_profile",
        },
        "logo_primary": {
            "asset_id": "logo_primary",
            "kind": "logo",
            "url": "https://example.com/logo.png",
            "source": "brand_profile",
        },
        "product_1": {
            "asset_id": "product_1",
            "kind": "product",
            "url": "https://example.com/product.jpg",
            "source": "brand_profile",
        },
        "dashboard_1": {
            "asset_id": "dashboard_1",
            "kind": "product",
            "url": "https://example.com/dashboard.jpg",
            "source": "brand_profile",
        },
    }
    return [by_id[asset_id] for asset_id in allowed_asset_ids]


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
                "body": "A concise story.",
                "asset_ids": ["hero_1"],
                "items": [],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "generous",
                    "background_role": "transparent",
                },
            },
            {
                "id": "cta",
                "order": 2,
                "type": "cta",
                "layout": "centered",
                "eyebrow": None,
                "headline": None,
                "body": None,
                "asset_ids": [],
                "items": [],
                "cta": {
                    "label": "Discover",
                    "url": "https://example.com/original",
                },
                "style": {
                    "alignment": "center",
                    "spacing": "generous",
                    "background_role": "transparent",
                },
            },
        ],
    }


def sample_revised_design_output():
    payload = sample_email_design()
    payload["sections"][0]["asset_ids"] = ["invented_asset", "hero_1"]
    payload["sections"][1]["cta"]["url"] = "https://attacker.example/phish"
    return payload


def sample_critique(revision_needed: bool):
    return {
        "schema_version": "1.0",
        "revision_needed": revision_needed,
        "summary": "Adjust hero hierarchy.",
        "strengths": ["Clear CTA cadence."],
        "issues": [
            {
                "category": "hierarchy",
                "severity": "major",
                "affected_section_ids": ["hero"],
                "observation": "Hero should dominate more.",
                "why_it_matters": "Reference direction is image-led.",
                "recommended_change": "Increase hero emphasis.",
            }
        ],
        "priority_changes": ["Increase hero dominance."],
    }


def sample_critique_metadata():
    return {
        "render_metadata": {
            "width": 760,
            "height": 980,
            "mime_type": "image/png",
            "image_diagnostics": {
                "total": 1,
                "loaded": 1,
                "broken": [],
            },
        },
        "compiler_errors": [],
    }


class RevisionServiceTests(TestCase):
    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_revision_attempts_are_bounded_and_constraints_are_preserved(self):
        client = Mock()
        client.interactions.create.side_effect = [
            SimpleNamespace(
                output_text=json.dumps(sample_revised_design_output())
            ),
            SimpleNamespace(
                output_text=json.dumps(sample_revised_design_output())
            ),
        ]
        reviser = GeminiEmailDesignReviser(client=client, critic=Mock())
        reviser._critique_design = Mock(
            side_effect=[
                (
                    DesignCritique.model_validate(sample_critique(True)),
                    sample_critique_metadata(),
                ),
                (
                    DesignCritique.model_validate(sample_critique(False)),
                    sample_critique_metadata(),
                ),
            ]
        )

        result = reviser.revise(
            brand_profile=sample_brand_profile(),
            email_design=sample_email_design(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(
                "Discover the collection",
                "https://example.com/product",
            ),
            fact_ledger=sample_fact_ledger(
                "Example",
                "https://example.com/product",
            ),
            asset_inventory=sample_assets(["hero_1", "logo_primary"]),
            design_critique=sample_critique(True),
            max_revision_attempts=2,
        )

        self.assertEqual(result["attempts_used"], 2)
        self.assertEqual(result["terminated_reason"], "approved")
        self.assertEqual(
            result["email_design"]["sections"][0]["asset_ids"],
            ["hero_1"],
        )
        self.assertEqual(
            result["email_design"]["sections"][1]["cta"]["url"],
            "https://example.com/product",
        )
        self.assertNotIn("developer_diagnostics", result)

    @override_settings(
        GEMINI_GENERATION_MODEL="gemini-test",
        EMAIL_DESIGN_REVISION_MAX_ATTEMPTS=1,
    )
    def test_revision_default_max_attempts_is_one(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(sample_revised_design_output())
        )
        reviser = GeminiEmailDesignReviser(client=client, critic=Mock())
        reviser._critique_design = Mock(
            return_value=(
                DesignCritique.model_validate(sample_critique(True)),
                sample_critique_metadata(),
            )
        )

        result = reviser.revise(
            brand_profile=sample_brand_profile(),
            email_design=sample_email_design(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(
                "Discover the collection",
                "https://example.com/product",
            ),
            fact_ledger=sample_fact_ledger(
                "Example",
                "https://example.com/product",
            ),
            asset_inventory=sample_assets(["hero_1", "logo_primary"]),
            design_critique=sample_critique(True),
        )

        self.assertEqual(result["max_attempts"], 1)
        self.assertEqual(result["attempts_used"], 1)
        self.assertEqual(
            result["terminated_reason"],
            "max_attempts_reached",
        )

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_failed_critic_preserves_last_valid_design(self):
        client = Mock()
        revised_output = sample_revised_design_output()
        revised_output["sections"][1]["cta"]["label"] = "Updated CTA"
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(revised_output)
        )
        reviser = GeminiEmailDesignReviser(client=client, critic=Mock())
        reviser._critique_design = Mock(
            side_effect=DesignCritiqueError("Critic downstream failed.")
        )

        result = reviser.revise(
            brand_profile=sample_brand_profile(),
            email_design=sample_email_design(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(
                "Discover the collection",
                "https://example.com/product",
            ),
            fact_ledger=sample_fact_ledger(
                "Example",
                "https://example.com/product",
            ),
            asset_inventory=sample_assets(["hero_1", "logo_primary"]),
            design_critique=sample_critique(True),
            max_revision_attempts=2,
        )

        self.assertFalse(result["completed"])
        self.assertEqual(result["terminated_reason"], "critic_failed")
        self.assertEqual(
            result["email_design"]["sections"][1]["cta"]["label"],
            "Updated CTA",
        )

    @patch("email_visual_qa.services.revision.capture_email_screenshot")
    @patch("email_visual_qa.services.revision.compile_mjml_to_html")
    @patch("email_visual_qa.services.revision.render_email_to_mjml")
    def test_critique_uses_rendered_screenshot_pipeline(
        self,
        render_mock,
        compile_mock,
        screenshot_mock,
    ):
        render_mock.return_value = {
            "mjml": "<mjml><mj-body></mj-body></mjml>",
            "rendered_sections": 2,
            "available_asset_ids": ["hero_1"],
        }
        compile_mock.return_value = {
            "html": "<!doctype html><html><body>ok</body></html>",
            "compiler_errors": [],
        }
        screenshot_mock.return_value = {
            "image_base64": "iVBORw0KGgoAAAANSUhEUg==",
            "mime_type": "image/png",
            "width": 760,
            "height": 980,
            "image_diagnostics": {
                "total": 1,
                "loaded": 1,
                "broken": [],
            },
        }
        critic = Mock()
        critic.critique.return_value = sample_critique(True)
        reviser = GeminiEmailDesignReviser(client=Mock(), critic=critic)

        critique, metadata = reviser._critique_design(
            brand=BrandProfile.model_validate(sample_brand_profile()),
            reference=ReferenceDesignSpec.model_validate(
                sample_reference_spec()
            ),
            assets=[
                AssetDescriptor.model_validate(item)
                for item in sample_assets(["hero_1"])
            ],
            email_design=EmailDesign.model_validate(sample_email_design()),
        )
        self.assertTrue(critique.revision_needed)
        self.assertEqual(metadata["render_metadata"]["width"], 760)
        render_mock.assert_called_once()
        compile_mock.assert_called_once()
        screenshot_mock.assert_called_once()

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_revision_can_include_developer_diagnostics(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(sample_revised_design_output())
        )
        reviser = GeminiEmailDesignReviser(client=client, critic=Mock())
        reviser._critique_design = Mock(
            return_value=(
                DesignCritique.model_validate(sample_critique(False)),
                sample_critique_metadata(),
            )
        )

        result = reviser.revise(
            brand_profile=sample_brand_profile(),
            email_design=sample_email_design(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(
                "Discover the collection",
                "https://example.com/product",
            ),
            fact_ledger=sample_fact_ledger(
                "Example",
                "https://example.com/product",
            ),
            asset_inventory=sample_assets(["hero_1", "logo_primary"]),
            design_critique=sample_critique(True),
            include_diagnostics=True,
        )
        self.assertIn("developer_diagnostics", result)


class RevisionRegressionFixturesTests(TestCase):
    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_regression_families_preserve_allowed_assets_and_authoritative_cta(
        self,
    ):
        fixtures_path = Path(__file__).parent / "regression_fixtures" / "design_families.json"
        with open(fixtures_path, encoding="utf-8") as handle:
            families = json.load(handle)

        for family in families:
            with self.subTest(family=family["family"]):
                client = Mock()
                revised = sample_revised_design_output()
                revised["sections"][1]["cta"]["label"] = family[
                    "expected_primary_action"
                ]
                client.interactions.create.return_value = SimpleNamespace(
                    output_text=json.dumps(revised)
                )
                reviser = GeminiEmailDesignReviser(
                    client=client,
                    critic=Mock(),
                )
                reviser._critique_design = Mock(
                    return_value=(
                        DesignCritique.model_validate(
                            sample_critique(False)
                        ),
                        sample_critique_metadata(),
                    )
                )

                result = reviser.revise(
                    brand_profile=sample_brand_profile(
                        family["brand_name"]
                    ),
                    email_design=sample_email_design(),
                    reference_design_spec=sample_reference_spec(),
                    content_plan=sample_content_plan(
                        family["expected_primary_action"],
                        family["destination_url"],
                    ),
                    fact_ledger=sample_fact_ledger(
                        family["brand_name"],
                        family["destination_url"],
                    ),
                    asset_inventory=sample_assets(
                        family["allowed_asset_ids"]
                    ),
                    design_critique=sample_critique(True),
                    max_revision_attempts=2,
                )

                final_design = result["email_design"]
                used_asset_ids = {
                    asset_id
                    for section in final_design["sections"]
                    for asset_id in section["asset_ids"]
                }
                self.assertTrue(
                    used_asset_ids.issubset(
                        set(family["allowed_asset_ids"])
                    )
                )
                self.assertEqual(
                    final_design["sections"][1]["cta"]["url"],
                    family["destination_url"],
                )
