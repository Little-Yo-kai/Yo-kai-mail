import json
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from .service import DemoGenerationError, generate_phase1_demo


@override_settings(
    WEBSITE_BRAND_CACHE_TTL_SECONDS=60, EMAIL_GENERATION_CACHE_TTL_SECONDS=60
)
class OfflineWorkflowTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "workflow.json").read_text(
                encoding="utf-8"
            )
        )
        self.mocks = {}
        for name in (
            "FirecrawlService",
            "GeminiBrandService",
            "GeminiCampaignStrategist",
            "GeminiEmailDesignComposer",
            "select_reference",
            "compile_mjml_to_html",
            "build_preview_html",
        ):
            patcher = patch(f"demo_flow.service.{name}")
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.mocks["FirecrawlService"].FORMATS = [
            "markdown",
            "branding",
            "images",
            "screenshot",
        ]
        self.mocks["FirecrawlService"].return_value.scrape.return_value = self.fixture[
            "scraped"
        ]
        self.mocks[
            "GeminiBrandService"
        ].return_value.analyze.return_value = self.fixture["brand_profile"]
        self.plan = self.mocks["GeminiCampaignStrategist"].return_value.plan
        self.plan.return_value = {
            key: self.fixture[key]
            for key in ("content_plan", "fact_ledger", "asset_inventory")
        }
        self.design = self.mocks["GeminiEmailDesignComposer"].return_value.compose
        self.design.return_value = {
            key: self.fixture[key] for key in ("email_design", "asset_inventory")
        }
        self.mocks["select_reference"].return_value = {
            "reference_id": "fixture",
            "name": "Fixture",
            "recipe_family": "intro",
            "selection_reasons": [],
            "reference_design_spec": self.fixture["reference_design_spec"],
        }
        self.mocks["compile_mjml_to_html"].return_value = {
            "html": "<html>Fixture</html>",
            "text": "Fixture",
            "compiler_errors": [],
        }
        self.mocks["build_preview_html"].return_value = ("<html>Preview</html>", [], [])

    def generate(self, **kwargs):
        return generate_phase1_demo(url=self.fixture["url"], **kwargs)

    def test_repeat_generation_uses_cached_analysis_and_design_but_refreshes_preview(
        self,
    ):
        first = self.generate()
        repeated = self.generate()
        self.assertEqual(first, repeated)
        self.mocks["FirecrawlService"].return_value.scrape.assert_called_once()
        self.mocks["GeminiBrandService"].return_value.analyze.assert_called_once()
        self.plan.assert_called_once()
        self.design.assert_called_once()
        self.assertEqual(self.mocks["build_preview_html"].call_count, 2)
        self.assertIn("<mjml>", first["render"]["mjml"])
        self.assertEqual(first["render"]["text"], "Fixture")

    def test_instructions_change_design_but_reuse_site_analysis(self):
        self.generate()
        self.generate(additional_instructions="Focus on the collection.")
        self.assertEqual(self.plan.call_count, 2)
        self.assertEqual(self.design.call_count, 2)
        self.mocks["GeminiBrandService"].return_value.analyze.assert_called_once()

    def test_model_changes_invalidate_generation(self):
        self.generate()
        with override_settings(GEMINI_GENERATION_MODEL="new-model"):
            self.generate()
        self.assertEqual(self.design.call_count, 2)

    def test_failed_generation_is_not_cached_and_stage_is_preserved(self):
        self.design.side_effect = RuntimeError("provider failed")
        with self.assertRaises(DemoGenerationError) as raised:
            self.generate()
        self.assertEqual(raised.exception.stage, "email_design")
        self.design.side_effect = None
        self.generate()
        self.assertEqual(self.design.call_count, 2)

    def test_brand_failure_is_not_cached_and_stage_is_preserved(self):
        analyze = self.mocks["GeminiBrandService"].return_value.analyze
        analyze.side_effect = ValueError("provider failed")
        with self.assertRaises(DemoGenerationError) as raised:
            self.generate()
        self.assertEqual(raised.exception.stage, "brand_analysis")
        analyze.side_effect = None
        self.generate()
        self.assertEqual(analyze.call_count, 2)

    def test_live_benchmark_requires_both_explicit_flags(self):
        for arguments in (("--live-url", "https://example.com"), ("--allow-paid-api",)):
            with self.subTest(arguments=arguments), self.assertRaises(CommandError):
                call_command("benchmark_email_workflow", *arguments)
        self.mocks["FirecrawlService"].return_value.scrape.assert_not_called()
        self.mocks["GeminiBrandService"].return_value.analyze.assert_not_called()
