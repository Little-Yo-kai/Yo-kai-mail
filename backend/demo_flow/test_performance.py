from contextlib import ExitStack
from threading import BoundedSemaphore, Event
from unittest.mock import patch

from django.core.cache import caches
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from campaigns.test_integrations import sample_brand_profile, sample_email_design
from email_visual_qa.test_revision import sample_reference_spec

from .service import generate_phase1_demo


class GenerationPerformanceTests(SimpleTestCase):
    def setUp(self):
        caches["generation"].clear()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.firecrawl = self.stack.enter_context(
            patch("demo_flow.service.FirecrawlService")
        )
        self.brand = self.stack.enter_context(
            patch("demo_flow.service.GeminiBrandService")
        )
        self.reference = self.stack.enter_context(
            patch("demo_flow.service.GeminiReferenceDesignService")
        )
        self.strategist = self.stack.enter_context(
            patch("demo_flow.service.GeminiCampaignStrategist")
        )
        self.composer = self.stack.enter_context(
            patch("demo_flow.service.GeminiEmailDesignComposer")
        )
        self.stack.enter_context(
            patch(
                "demo_flow.service.compile_mjml_to_html",
                return_value={
                    "html": "<html>Email</html>",
                    "compiler_errors": [],
                },
            )
        )
        self.stack.enter_context(
            patch(
                "demo_flow.service.build_preview_html",
                return_value=("<html>Email</html>", [], []),
            )
        )
        self.firecrawl.return_value.scrape.return_value = {"markdown": "# Example"}
        self.brand.return_value.analyze.return_value = sample_brand_profile()
        self.reference.return_value.analyze.return_value = sample_reference_spec()
        self.strategist.return_value.plan.return_value = {
            "content_plan": {},
            "asset_inventory": [],
            "fact_ledger": {},
        }
        self.composer.return_value.compose.return_value = {
            "email_design": sample_email_design(),
            "asset_inventory": [],
        }

    def generate(self, **kwargs):
        return generate_phase1_demo(
            url=kwargs.pop("url", "https://example.com"), **kwargs
        )

    def test_repeat_reuses_preparation_and_still_composes_fresh_email(self):
        first = self.generate()
        repeated = self.generate()
        self.assertEqual(self.firecrawl.return_value.scrape.call_count, 1)
        self.assertEqual(self.brand.return_value.analyze.call_count, 1)
        self.assertEqual(self.strategist.return_value.plan.call_count, 1)
        self.assertEqual(self.composer.return_value.compose.call_count, 2)
        self.assertEqual(first["performance"]["reused_stages"], [])
        self.assertEqual(
            repeated["performance"]["reused_stages"],
            [
                "website_import",
                "brand_analysis",
                "content_plan",
            ],
        )
        self.assertGreaterEqual(repeated["performance"]["total_seconds"], 0)

    def test_instructions_models_and_refresh_invalidate_relevant_work(self):
        self.generate()
        self.generate(additional_instructions="Focus on materials")
        self.assertEqual(self.firecrawl.return_value.scrape.call_count, 1)
        self.assertEqual(self.strategist.return_value.plan.call_count, 2)
        with self.settings(GEMINI_MODEL="different-model"):
            self.generate()
        self.assertEqual(self.brand.return_value.analyze.call_count, 2)
        self.generate(refresh_website=True)
        self.assertEqual(self.firecrawl.return_value.scrape.call_count, 2)
        self.assertEqual(self.brand.return_value.analyze.call_count, 3)
        self.generate(url="https://example.com/other")
        self.assertEqual(self.firecrawl.return_value.scrape.call_count, 3)

    def test_uploaded_reference_starts_during_website_read_and_reuses_by_bytes(self):
        entered, release = Event(), Event()

        def analyze(image):
            self.assertEqual(image.read(), b"reference")
            entered.set()
            self.assertTrue(release.wait(2))
            return sample_reference_spec()

        def scrape(url):
            self.assertTrue(
                entered.wait(1), "Reference was not started alongside website reading"
            )
            release.set()
            return {"markdown": "# Example"}

        self.reference.return_value.analyze.side_effect = analyze
        self.firecrawl.return_value.scrape.side_effect = scrape
        for _ in range(2):
            with SimpleUploadedFile(
                "ref.png", b"reference", content_type="image/png"
            ) as image:
                self.generate(reference_image=image)
        self.reference.return_value.analyze.assert_called_once()

    def test_reference_capacity_exhaustion_falls_back_to_inline_analysis(self):
        slots = BoundedSemaphore(1)
        slots.acquire()
        with (
            patch("demo_flow.preparation._reference_slots", slots),
            SimpleUploadedFile(
                "ref.png", b"reference", content_type="image/png"
            ) as image,
        ):
            result = self.generate(reference_image=image)
        self.assertEqual(result["mode"], "uploaded_reference")
        self.reference.return_value.analyze.assert_called_once()
