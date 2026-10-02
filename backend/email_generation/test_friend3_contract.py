import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import override_settings
from pydantic import ValidationError
from rest_framework.test import APITestCase

from .builders import build_asset_inventory, build_fact_ledger
from .schemas import EmailDesign
from .services.composer import EmailDesignGenerationError, GeminiEmailDesignComposer
from .services.regeneration import GeminiSectionRegenerator
from .services.validation import EmailDesignContractError, validate_email_design_contract
from .tests import (
    sample_brand_profile,
    sample_campaign_brief,
    sample_content_plan,
    sample_email_design,
    sample_reference_spec,
)


class Friend3EmailDesignContractTests(APITestCase):
    def _assets(self):
        return [
            asset.model_dump(mode="json")
            for asset in build_asset_inventory(sample_brand_profile())
        ]

    def _facts(self):
        return build_fact_ledger(sample_brand_profile(), sample_campaign_brief())

    def test_all_supported_section_types_validate(self):
        section_types = [
            ("hero", {"headline": "Hero"}),
            ("intro", {"body": "Intro copy"}),
            ("product_feature", {"body": "Feature copy"}),
            ("product_grid", {"items": [{"title": "Product"}]}),
            ("benefits", {"items": [{"title": "Benefit"}]}),
            ("lifestyle", {"body": "Lifestyle copy"}),
            ("offer", {"body": "Offer copy"}),
            ("cta", {"cta": {"label": "Discover", "url": "https://example.com/product"}}),
            ("footer", {"body": "Footer copy"}),
        ]
        design = sample_email_design()
        sections = []
        for index, (section_type, extra) in enumerate(section_types, start=1):
            section = {
                "id": section_type,
                "order": index,
                "type": section_type,
                "layout": "centered" if section_type != "product_grid" else "grid_2",
                "eyebrow": None,
                "headline": None,
                "body": None,
                "asset_ids": [],
                "items": [],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "balanced",
                    "background_role": "transparent",
                },
            }
            section.update(extra)
            sections.append(section)
        design["sections"] = sections
        design["subject"] = "Subject"
        design["preheader"] = "Preheader"

        validated = validate_email_design_contract(
            design,
            asset_inventory=self._assets(),
            fact_ledger=self._facts(),
        )
        self.assertEqual(len(validated.sections), 9)

    def test_invalid_asset_is_rejected_by_application_contract(self):
        design = sample_email_design()
        design["sections"][0]["asset_ids"] = ["invented_asset"]
        with self.assertRaises(EmailDesignContractError):
            validate_email_design_contract(
                design,
                asset_inventory=self._assets(),
                fact_ledger=self._facts(),
            )

    def test_invalid_cta_is_rejected_by_application_contract(self):
        design = sample_email_design()
        design["sections"][1]["cta"]["url"] = "https://evil.example"
        with self.assertRaises(EmailDesignContractError):
            validate_email_design_contract(
                design,
                asset_inventory=self._assets(),
                fact_ledger=self._facts(),
            )

    def test_version_compatibility_is_explicit(self):
        legacy = sample_email_design()
        legacy["schema_version"] = "1.0"
        validate_email_design_contract(
            legacy, asset_inventory=self._assets(), fact_ledger=self._facts()
        )

        current = copy.deepcopy(legacy)
        current["schema_version"] = "1.1"
        current["alternative_subjects"] = ["A different subject"]
        current["content_variants"] = [{
            "variant_id": "control",
            "subject": current["subject"],
            "preheader": current["preheader"],
            "sections": current["sections"],
        }]
        validate_email_design_contract(
            current,
            asset_inventory=self._assets(),
            fact_ledger=self._facts(),
            require_current_version=True,
        )

        unknown = copy.deepcopy(current)
        unknown["schema_version"] = "9.0"
        with self.assertRaises(EmailDesignContractError):
            validate_email_design_contract(
                unknown, asset_inventory=self._assets(), fact_ledger=self._facts()
            )

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_generation_failure_has_stage_and_reason(self):
        client = Mock()
        client.interactions.create.side_effect = RuntimeError("provider down")
        composer = GeminiEmailDesignComposer(client=client)

        with self.assertRaises(EmailDesignGenerationError) as ctx:
            composer.compose(
                brand_profile=sample_brand_profile(),
                reference_design_spec=sample_reference_spec(),
                content_plan=sample_content_plan(),
                asset_inventory=self._assets(),
                fact_ledger=self._facts().model_dump(mode="json"),
            )

        self.assertEqual(ctx.exception.stage, "email_design_generation")
        self.assertEqual(ctx.exception.reason, "Generation request failed")

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_invalid_structured_output_has_stage_and_reason(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text='{"schema_version":"1.1","sections":[]}'
        )
        composer = GeminiEmailDesignComposer(client=client)

        with self.assertRaises(EmailDesignGenerationError) as ctx:
            composer.compose(
                brand_profile=sample_brand_profile(),
                reference_design_spec=sample_reference_spec(),
                content_plan=sample_content_plan(),
                asset_inventory=self._assets(),
                fact_ledger=self._facts().model_dump(mode="json"),
            )

        self.assertEqual(ctx.exception.stage, "email_design_generation")
        self.assertEqual(ctx.exception.reason, "Invalid structured output")

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_variants_and_alternative_subjects_are_supported(self):
        design = sample_email_design()
        design["schema_version"] = "1.1"
        design["alternative_subjects"] = [
            "Discover the new expression",
            "A considered icon",
        ]
        design["content_variants"] = [{
            "variant_id": "control",
            "subject": design["subject"],
            "preheader": design["preheader"],
            "sections": design["sections"],
        }]
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(design)
        )
        result = GeminiEmailDesignComposer(client=client).compose(
            brand_profile=sample_brand_profile(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(),
            asset_inventory=self._assets(),
            fact_ledger=self._facts().model_dump(mode="json"),
        )
        self.assertEqual(result["email_design"]["schema_version"], "1.1")
        self.assertEqual(
            result["email_design"]["alternative_subjects"][0],
            "Discover the new expression",
        )

    def test_schema_rejects_missing_required_fields(self):
        design = sample_email_design()
        design.pop("subject")
        with self.assertRaises(ValidationError):
            EmailDesign.model_validate(design)


class SectionRegenerationTests(APITestCase):
    def _assets(self):
        return [
            asset.model_dump(mode="json")
            for asset in build_asset_inventory(sample_brand_profile())
        ]

    def _facts(self):
        return build_fact_ledger(sample_brand_profile(), sample_campaign_brief())

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_only_selected_section_changes_and_approved_cta_url_is_preserved(self):
        current = sample_email_design()
        current["sections"].insert(
            1,
            {
                "id": "intro",
                "order": 2,
                "type": "intro",
                "layout": "centered",
                "eyebrow": "INTRO",
                "headline": "Original introduction",
                "body": "Original approved campaign copy.",
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
        current["sections"][2]["order"] = 3

        regenerated = copy.deepcopy(current["sections"][1])
        regenerated["headline"] = "Regenerated introduction"
        regenerated["body"] = "New copy for this section only."

        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text=json.dumps(regenerated)
        )

        result = GeminiSectionRegenerator(client=client).regenerate(
            current_design=current,
            section_id="intro",
            brand_profile=sample_brand_profile(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(),
            asset_inventory=self._assets(),
            fact_ledger=self._facts().model_dump(mode="json"),
        )
        updated = result["email_design"]

        self.assertEqual(updated["subject"], current["subject"])
        self.assertEqual(updated["preheader"], current["preheader"])
        self.assertEqual(updated["theme"], current["theme"])
        self.assertEqual(updated["sections"][0], current["sections"][0])
        self.assertEqual(updated["sections"][2], current["sections"][2])
        self.assertEqual(updated["sections"][1]["id"], "intro")
        self.assertEqual(updated["sections"][1]["headline"], "Regenerated introduction")
        self.assertEqual(
            updated["sections"][2]["cta"]["url"],
            self._facts().authoritative_destination_url,
        )

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_regeneration_rejects_unknown_section(self):
        client = Mock()
        with self.assertRaises(EmailDesignGenerationError) as ctx:
            GeminiSectionRegenerator(client=client).regenerate(
                current_design=sample_email_design(),
                section_id="missing",
                brand_profile=sample_brand_profile(),
                reference_design_spec=sample_reference_spec(),
                content_plan=sample_content_plan(),
                asset_inventory=self._assets(),
                fact_ledger=self._facts().model_dump(mode="json"),
            )
        self.assertEqual(ctx.exception.reason, "Section not found")
