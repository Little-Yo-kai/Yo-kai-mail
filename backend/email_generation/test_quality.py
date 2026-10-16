import json
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase, override_settings

from .builders import build_asset_inventory, build_fact_ledger
from .services.composer import GeminiEmailDesignComposer
from .services.validation import (
    EmailDesignContractError,
    lint_email_design,
    validate_email_design_contract,
)
from .test_friend3_contract import sample_email_design
from .tests import (
    sample_brand_profile,
    sample_campaign_brief,
    sample_content_plan,
    sample_reference_spec,
)


class EmailDesignQualityTests(SimpleTestCase):
    def setUp(self):
        self.assets = build_asset_inventory(sample_brand_profile())
        self.facts = build_fact_ledger(sample_brand_profile(), sample_campaign_brief())

    def test_contract_rejects_blank_cta_labels_and_malformed_destinations(self):
        for label, url in [
            ("  ", "https://example.com/product"),
            ("Discover", "https://user:password@example.com/product"),
            ("Discover", "https://example.com:bad/product"),
            ("Discover", "https://[invalid/product"),
            ("Discover", "https://example.com/\nproduct"),
            ("Discover", "https://example.com\\@evil.example/product"),
        ]:
            with self.subTest(label=label, url=url):
                design = sample_email_design()
                design["sections"][1]["cta"] = {"label": label, "url": url}
                with self.assertRaises(EmailDesignContractError):
                    validate_email_design_contract(
                        design, asset_inventory=self.assets, fact_ledger=self.facts,
                    )

    def test_footer_quality_warning_is_nonblocking_for_legacy_designs(self):
        design = validate_email_design_contract(
            sample_email_design(), asset_inventory=self.assets, fact_ledger=self.facts,
        )
        self.assertEqual(design.schema_version, "1.0")
        self.assertIn("missing-footer", [item["code"] for item in lint_email_design(design)])

    @override_settings(GEMINI_GENERATION_MODEL="gemini-test")
    def test_missing_cta_label_recovers_without_another_model_request(self):
        design = sample_email_design()
        design["sections"][1]["cta"]["label"] = " "
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(output_text=json.dumps(design))
        result = GeminiEmailDesignComposer(client=client).compose(
            brand_profile=sample_brand_profile(),
            reference_design_spec=sample_reference_spec(),
            content_plan=sample_content_plan(),
            asset_inventory=[asset.model_dump(mode="json") for asset in self.assets],
            fact_ledger=self.facts.model_dump(mode="json"),
        )
        self.assertEqual(client.interactions.create.call_count, 1)
        self.assertEqual(
            result["email_design"]["sections"][1]["cta"]["label"],
            sample_content_plan()["cta_strategy"]["primary_action"],
        )
        self.assertTrue(result["recovery_actions"])
