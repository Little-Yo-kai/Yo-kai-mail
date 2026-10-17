import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase, override_settings

from brand_intelligence.schemas import BrandProfile
from demo_flow.prompt_benchmark import (
    capture_fixture_generation,
    measure_prompt_context,
)
from reference_design.schemas import ReferenceDesignSpec

from .builders import build_asset_inventory, build_fact_ledger
from .schemas import EmailDesign
from .services.composer import GeminiEmailDesignComposer


class PromptContextTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fixture = json.loads(
            (Path(__file__).resolve().parents[1] / "demo_flow" / "fixtures" / "workflow.json")
            .read_text(encoding="utf-8")
        )

    @staticmethod
    def payload(request):
        return json.loads(request["input"].split("\n\nINPUT JSON:\n", 1)[1])

    def test_actual_requests_preserve_every_context_value_and_validated_output(self):
        before = capture_fixture_generation(self.fixture, compact=False)
        after = capture_fixture_generation(self.fixture, compact=True)
        self.assertEqual(before["planned"], after["planned"])
        self.assertEqual(before["composed"], after["composed"])
        self.assertEqual(len(before["requests"]), 2)
        self.assertEqual(len(after["requests"]), 2)
        for full, compact in zip(before["requests"], after["requests"], strict=True):
            self.assertEqual(self.payload(full), self.payload(compact))
            self.assertEqual(full["response_format"], compact["response_format"])
            self.assertEqual(full["model"], compact["model"])
            self.assertLess(len(compact["input"].encode()), len(full["input"].encode()))

        strategy, composer = map(self.payload, after["requests"])
        expected_assets = [
            asset.model_dump(mode="json")
            for asset in build_asset_inventory(self.fixture["brand_profile"])
        ]
        expected_facts = build_fact_ledger(
            self.fixture["brand_profile"], self.fixture["campaign_brief"]
        ).model_dump(mode="json")
        self.assertEqual(strategy["brand_profile"], self.fixture["brand_profile"])
        self.assertEqual(strategy["campaign_brief"], self.fixture["campaign_brief"])
        self.assertEqual(strategy["reference_design_spec"], self.fixture["reference_design_spec"])
        self.assertEqual(composer["brand_profile"], BrandProfile.model_validate(self.fixture["brand_profile"]).model_dump(mode="json"))
        self.assertEqual(composer["reference_design_spec"], ReferenceDesignSpec.model_validate(self.fixture["reference_design_spec"]).model_dump(mode="json"))
        for context in (strategy, composer):
            self.assertEqual(context["asset_inventory"], expected_assets)
            self.assertEqual(context["fact_ledger"], expected_facts)
        self.assertEqual(composer["content_plan"], after["planned"]["content_plan"])
        self.assertEqual(composer["content_plan"]["cta_strategy"]["destination_url"], expected_facts["authoritative_destination_url"])
        design = EmailDesign.model_validate(after["composed"]["email_design"])
        self.assertEqual(design.theme.model_dump(mode="json"), self.fixture["email_design"]["theme"])
        self.assertTrue(any(section.cta for section in design.sections))
        for section in design.sections:
            if section.cta:
                self.assertEqual(section.cta.url, expected_facts["authoritative_destination_url"])

    def test_measurements_emit_only_aggregate_sizes_and_equalities(self):
        measured = measure_prompt_context(self.fixture)
        self.assertTrue(measured["contexts_equal"])
        self.assertTrue(measured["validated_outputs_equal"])
        self.assertTrue(measured["response_schemas_equal"])
        self.assertEqual(measured["model_calls_per_mode"], {"strategist": 1, "composer": 1})
        for stage in ("strategist", "composer"):
            self.assertLess(measured["compact"][stage]["prompt_utf8_bytes"], measured["baseline"][stage]["prompt_utf8_bytes"])
            self.assertEqual(measured["compact"][stage]["response_schema_utf8_bytes"], measured["baseline"][stage]["response_schema_utf8_bytes"])
        encoded = json.dumps(measured)
        self.assertNotIn(self.fixture["campaign_brief"]["destination_url"], encoded)
        self.assertNotIn(self.fixture["email_design"]["subject"], encoded)

    def test_existing_single_repair_path_is_preserved_in_both_modes(self):
        invalid = deepcopy(self.fixture["email_design"])
        invalid["sections"].append({
            **invalid["sections"][0], "id": "empty_grid", "order": 3,
            "type": "product_grid", "layout": "grid_2", "body": None,
            "asset_ids": [], "items": [], "cta": None,
        })
        outputs = []
        for compact in (False, True):
            with self.subTest(compact=compact), override_settings(GEMINI_COMPACT_CONTEXT_ENABLED=compact):
                client = Mock()
                client.interactions.create.side_effect = [
                    SimpleNamespace(output_text=json.dumps(invalid)),
                    SimpleNamespace(output_text=json.dumps(self.fixture["email_design"])),
                ]
                outputs.append(GeminiEmailDesignComposer(client=client).compose(
                    **{key: self.fixture[key] for key in (
                        "brand_profile", "reference_design_spec", "content_plan",
                        "asset_inventory", "fact_ledger",
                    )},
                ))
                self.assertEqual(client.interactions.create.call_count, 2)
                first, repair = client.interactions.create.call_args_list
                self.assertTrue(repair.kwargs["input"].startswith(first.kwargs["input"] + "\n\nREPAIR TASK:"))
        self.assertEqual(outputs[0], outputs[1])
