import json
import time
from threading import BoundedSemaphore, Event
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import AsyncClient, SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APISimpleTestCase

from campaigns.test_integrations import sample_brand_profile, sample_email_design
from core.generation_budget import GenerationBudget, generation_budget, report_stage
from email_visual_qa.test_revision import sample_reference_spec

from .preview import build_preview_html
from .runner import GenerationBusy, GenerationRun
from .service import DemoGenerationError, generate_phase1_demo


class GenerationRunnerTests(SimpleTestCase):
    @override_settings(DEMO_GENERATION_TIMEOUT_SECONDS=0.03)
    def test_blocked_provider_returns_deadline_error_without_waiting_for_worker(self):
        release = Event()
        run = GenerationRun(lambda: release.wait(2))
        started = time.monotonic()
        try:
            events = list(run.events())
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(run.thread.is_alive())
            self.assertEqual(events[-1]["code"], "generation_timeout")
            self.assertEqual(events[-1]["status"], 504)
            self.assertTrue(run.budget.cancelled.is_set())
        finally:
            release.set()
            run.thread.join(1)

    def test_disconnect_prevents_following_stage_and_releases_capacity(self):
        release = Event()
        next_provider = Mock()

        def generate():
            report_stage("website_import")
            release.wait(2)
            report_stage("brand_analysis")
            next_provider()

        with patch("demo_flow.runner._slots", BoundedSemaphore(1)):
            run = GenerationRun(generate)
            try:
                events = run.events()
                next(events)
                self.assertEqual(next(events)["stage"], "website_import")
                events.close()
                with self.assertRaises(GenerationBusy):
                    GenerationRun(dict)
            finally:
                release.set()
                run.thread.join(1)
            next_provider.assert_not_called()
            retry = GenerationRun(lambda: {"ok": True})
            self.assertTrue(list(retry.events())[-1]["success"])
            retry.thread.join(1)


class GenerationProgressApiTests(APISimpleTestCase):
    @patch("demo_flow.views.generate_phase1_demo")
    def test_stream_forwards_uploaded_image_and_real_progress(self, generate):
        def pipeline(**kwargs):
            self.assertEqual(kwargs["reference_image"].read(), b"reference-bytes")
            report_stage("website_import")
            report_stage("reference_selection")
            return {"render": {"html": "<html>Generated</html>"}}

        generate.side_effect = pipeline
        response = self.client.post(
            reverse("phase1-demo-generate-stream"),
            {
                "url": "https://example.com",
                "reference_image": SimpleUploadedFile(
                    "ref.png", b"reference-bytes", content_type="image/png"
                ),
            },
            format="multipart",
        )
        events = [json.loads(chunk) for chunk in response.streaming_content]
        self.assertEqual(response["Content-Type"], "application/x-ndjson")
        self.assertEqual(response["X-Accel-Buffering"], "no")
        self.assertEqual(events[0]["type"], "started")
        self.assertEqual(
            [e["stage"] for e in events if e["type"] == "progress"],
            ["website_import", "reference_selection"],
        )
        self.assertTrue(events[-1]["success"])
        self.assertIn("Generated", events[-1]["data"]["render"]["html"])

    @override_settings(DEBUG=False)
    @patch("demo_flow.views.generate_phase1_demo")
    def test_json_and_stream_explain_wrapped_provider_errors_without_leaking_details(
        self, generate
    ):
        for details, code, status in [
            ("Read timed out; secret-key", "generation_timeout", 504),
            ("HTTP 503 high demand; secret-key", "provider_busy", 503),
            ("HTTP 429 rate limit; secret-key", "provider_rate_limited", 429),
        ]:
            generate.side_effect = DemoGenerationError(
                "brand_analysis", "Analysis failed", details=details
            )
            for streaming in (False, True):
                with self.subTest(code=code, streaming=streaming):
                    response = self.client.post(
                        reverse(
                            "phase1-demo-generate-stream"
                            if streaming
                            else "phase1-demo-generate"
                        ),
                        {"url": "https://example.com"},
                        format="multipart",
                    )
                    payload = (
                        [json.loads(c) for c in response.streaming_content][-1]
                        if streaming
                        else response.data
                    )
                    self.assertEqual(payload["code"], code)
                    self.assertEqual(
                        payload.get("status", response.status_code), status
                    )
                    self.assertEqual(payload["stage"], "brand_analysis")
                    self.assertNotIn("secret-key", json.dumps(payload))
                    self.assertNotIn("details", payload)

    @patch("demo_flow.views.generate_phase1_demo")
    def test_invalid_upload_is_rejected_before_worker_starts(self, generate):
        response = self.client.post(
            reverse("phase1-demo-generate-stream"),
            {
                "url": "https://example.com",
                "reference_image": SimpleUploadedFile(
                    "ref.txt", b"not image", content_type="text/plain"
                ),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        generate.assert_not_called()

    @patch(
        "demo_flow.views.generate_phase1_demo",
        return_value={"render": {"html": "<html>ASGI</html>"}},
    )
    async def test_asgi_response_uses_async_stream_instead_of_buffering(self, generate):
        response = await AsyncClient().post(
            reverse("phase1-demo-generate-stream"), {"url": "https://example.com"}
        )
        self.assertTrue(response.is_async)
        events = [json.loads(chunk) async for chunk in response.streaming_content]
        self.assertTrue(events[-1]["success"])


class PreviewCompletionTests(SimpleTestCase):
    @override_settings(DEMO_PREVIEW_TIMEOUT_SECONDS=0.03)
    @patch("demo_flow.preview._build_preview_html")
    def test_stalled_preview_cannot_hold_back_compiled_email(self, build):
        release = Event()
        finished = Event()

        def stalled(**kwargs):
            release.wait(2)
            finished.set()
            return "late preview", [], []

        build.side_effect = stalled
        html = '<html><img src="https://example.com/hero.png"></html>'
        started = time.monotonic()
        try:
            preview, diagnostics, assets = build_preview_html(
                html_document=html,
                asset_inventory=[{"url": "https://example.com/hero.png"}],
            )
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertEqual(preview, html)
            self.assertEqual(diagnostics[0]["status"], "unavailable")
            self.assertEqual(assets, [])
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

    @override_settings(DEMO_PREVIEW_TIMEOUT_SECONDS=0)
    @patch("demo_flow.preview.cleanup_expired_email_assets")
    @patch("demo_flow.preview.get_or_cache_remote_image")
    def test_expired_preview_budget_preserves_original_html_without_downloads(
        self, cache, cleanup
    ):
        html = '<html><img src="https://example.com/hero.png"></html>'
        preview, diagnostics, assets = build_preview_html(
            html_document=html,
            asset_inventory=[{"url": "https://example.com/hero.png"}],
        )
        self.assertEqual(preview, html)
        self.assertEqual(diagnostics[0]["status"], "unavailable")
        self.assertEqual(assets, [])
        cache.assert_not_called()

    @patch(
        "demo_flow.service.build_preview_html",
        side_effect=OSError("Cache disk unavailable"),
    )
    @patch(
        "demo_flow.service.compile_mjml_to_html",
        return_value={"html": "<html>Generated email</html>", "compiler_errors": []},
    )
    @patch("demo_flow.service.GeminiEmailDesignComposer")
    @patch("demo_flow.service.GeminiCampaignStrategist")
    @patch("demo_flow.service.GeminiReferenceDesignService")
    @patch("demo_flow.service.GeminiBrandService")
    @patch("demo_flow.service.FirecrawlService")
    def test_uploaded_image_pipeline_keeps_compiled_email_when_preview_cache_fails(
        self,
        firecrawl,
        brand,
        reference,
        strategist,
        composer,
        compiler,
        preview,
    ):
        firecrawl.return_value.scrape.return_value = {"markdown": "Example"}
        brand.return_value.analyze.return_value = sample_brand_profile()
        reference.return_value.analyze.return_value = sample_reference_spec()
        strategist.return_value.plan.return_value = {
            "content_plan": {},
            "asset_inventory": [],
            "fact_ledger": {},
        }
        composer.return_value.compose.return_value = {
            "email_design": sample_email_design(),
            "asset_inventory": [],
        }
        events = []
        with generation_budget(GenerationBudget(on_progress=events.append)):
            result = generate_phase1_demo(
                url="https://example.com",
                reference_image=SimpleUploadedFile(
                    "ref.png", b"image", content_type="image/png"
                ),
            )
        self.assertEqual(result["mode"], "uploaded_reference")
        reference.return_value.analyze.assert_called_once()
        self.assertEqual(result["render"]["html"], "<html>Generated email</html>")
        self.assertEqual(result["render"]["preview_html"], result["render"]["html"])
        self.assertEqual(result["render"]["cached_assets"], [])
        self.assertEqual(
            [e["stage"] for e in events],
            [
                "website_import",
                "brand_analysis",
                "reference_selection",
                "content_plan",
                "email_design",
                "render",
                "preview_assets",
            ],
        )
