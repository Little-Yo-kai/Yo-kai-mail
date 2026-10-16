"""Exercise capacity recovery through the installed SDK without network calls."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from google import genai
from google.genai._gaos.lib.compat_errors import InternalServerError

from core.ai_fallback import call_with_model_fallback
from core.gemini_client import create_gemini_client, gemini_json_schema
from core.generation_budget import (
    GenerationBudget,
    GenerationTimedOut,
    generation_budget,
)

from .builders import normalize_email_design
from .schemas import AssetDescriptor, EmailDesign, FactLedger
from .services.composer import EmailDesignGenerationError, GeminiEmailDesignComposer
from .services.validation import validate_email_design_contract

PRIMARY = "gemini-3.8-flash"
CONFIGURED_FALLBACK = "gemini-3.1-flash-lite"
ADDITIONAL_FALLBACK = "gemini-3.5-flash-lite"
PRIVATE_PROMPT_MARKER = "PRIVATE_CAPACITY_PROMPT_SENTINEL"


@override_settings(
    GEMINI_GENERATION_MODEL=PRIMARY,
    GEMINI_FALLBACK_MODEL=CONFIGURED_FALLBACK,
    GEMINI_ADDITIONAL_FALLBACK_MODELS=[ADDITIONAL_FALLBACK],
    GEMINI_REQUEST_TIMEOUT_SECONDS=6,
)
class GeminiCapacityRecoveryTests(SimpleTestCase):
    def setUp(self):
        fixture_path = Path(__file__).resolve().parents[1] / "demo_flow" / "fixtures" / "workflow.json"
        self.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.fixture["content_plan"]["strategic_rationale"] = PRIVATE_PROMPT_MARKER
        self.design = normalize_email_design(
            EmailDesign.model_validate(self.fixture["email_design"]),
            asset_inventory=[AssetDescriptor.model_validate(item) for item in self.fixture["asset_inventory"]],
            fact_ledger=FactLedger.model_validate(self.fixture["fact_ledger"]),
        ).model_dump(mode="json")
        self.requests = []

    def make_client(self, respond):
        def capture(request):
            self.requests.append(request)
            return respond(request)

        def factory(**kwargs):
            return genai.Client(**{
                **kwargs,
                "http_options": {
                    **kwargs["http_options"],
                    "httpx_client": httpx.Client(
                        transport=httpx.MockTransport(capture), trust_env=False,
                    ),
                    "async_client_args": {"trust_env": False},
                },
            })

        client = create_gemini_client(api_key="offline-test-key", client_factory=factory)
        self.addCleanup(client.close)
        return client

    @staticmethod
    def overloaded(status=503, message="Model is experiencing high demand"):
        return httpx.Response(
            status,
            headers={"Retry-After": "1800"},
            json={"error": {"code": status, "status": "UNAVAILABLE", "message": message}},
        )

    def completed(self):
        return httpx.Response(200, json={
            "id": "offline-capacity-fixture",
            "status": "completed",
            "steps": [{
                "type": "model_output",
                "content": [{"type": "text", "text": json.dumps(self.design)}],
            }],
        })

    def compose(self, client):
        return GeminiEmailDesignComposer(client=client).compose(**{
            key: self.fixture[key]
            for key in ("brand_profile", "reference_design_spec", "content_plan", "asset_inventory", "fact_ledger")
        })

    def models_requested(self):
        return [json.loads(request.content)["model"] for request in self.requests]

    @patch("core.ai_fallback.time.sleep")
    def test_composer_recovers_on_distinct_third_model_with_schema_and_safe_logs(self, sleep):
        client = self.make_client(
            lambda request: self.completed() if len(self.requests) == 3 else self.overloaded()
        )
        with (
            generation_budget(GenerationBudget(seconds=7)),
            self.assertLogs("yokai.workflow", level="INFO") as logs,
            self.assertLogs("core.ai_fallback", level="WARNING") as fallback_logs,
        ):
            result = self.compose(client)

        self.assertEqual(self.models_requested(), [PRIMARY, CONFIGURED_FALLBACK, ADDITIONAL_FALLBACK])
        self.assertEqual(result["email_design"], self.design)
        validate_email_design_contract(
            result["email_design"], asset_inventory=self.fixture["asset_inventory"],
            fact_ledger=self.fixture["fact_ledger"],
        )
        for request in self.requests:
            payload = json.loads(request.content)
            self.assertEqual(payload["response_format"]["schema"], gemini_json_schema(EmailDesign))
            self.assertIn(PRIVATE_PROMPT_MARKER, payload["input"])
            self.assertGreater(request.extensions["timeout"]["read"], 0)
            self.assertLessEqual(request.extensions["timeout"]["read"], 6)
        logged = "\n".join(logs.output + fallback_logs.output)
        self.assertNotIn(PRIVATE_PROMPT_MARKER, logged)
        self.assertNotIn("offline-test-key", logged)
        sleep.assert_not_called()

    @patch("core.ai_fallback.time.sleep")
    def test_all_three_overloaded_stops_without_fabricating_a_design(self, sleep):
        client = self.make_client(lambda request: self.overloaded())
        with self.assertRaises(EmailDesignGenerationError) as raised:
            self.compose(client)
        self.assertEqual(self.models_requested(), [PRIMARY, CONFIGURED_FALLBACK, ADDITIONAL_FALLBACK])
        self.assertEqual(raised.exception.reason, "Generation request failed")
        self.assertIsInstance(raised.exception.__cause__, InternalServerError)
        self.assertEqual(raised.exception.__cause__.status_code, 503)
        sleep.assert_not_called()

    @patch("core.ai_fallback.time.sleep")
    def test_known_client_errors_fail_fast_even_with_capacity_words(self, sleep):
        for status in (400, 401, 403):
            with self.subTest(status=status):
                self.requests = []
                client = self.make_client(lambda request, status=status: self.overloaded(status))
                with self.assertRaises(EmailDesignGenerationError) as raised:
                    self.compose(client)
                self.assertEqual(self.models_requested(), [PRIMARY])
                self.assertEqual(raised.exception.__cause__.status_code, status)
        sleep.assert_not_called()

    @patch("core.ai_fallback.time.sleep")
    def test_rate_limits_try_distinct_models_without_retrying_the_last_model(self, sleep):
        client = self.make_client(lambda request: self.overloaded(429, "Rate limit exceeded"))
        with self.assertRaises(EmailDesignGenerationError) as raised:
            self.compose(client)
        self.assertEqual(self.models_requested(), [PRIMARY, CONFIGURED_FALLBACK, ADDITIONAL_FALLBACK])
        self.assertEqual(raised.exception.__cause__.status_code, 429)
        sleep.assert_not_called()

    @patch("core.ai_fallback.time.sleep")
    def test_duplicate_extra_models_and_long_configuration_remain_bounded(self, sleep):
        client = self.make_client(lambda request: self.overloaded())
        with self.settings(GEMINI_ADDITIONAL_FALLBACK_MODELS=[
            PRIMARY, CONFIGURED_FALLBACK, ADDITIONAL_FALLBACK, "unused-fourth-model",
        ]), self.assertRaises(EmailDesignGenerationError):
            self.compose(client)
        self.assertEqual(self.models_requested(), [PRIMARY, CONFIGURED_FALLBACK, ADDITIONAL_FALLBACK])
        sleep.assert_not_called()

    @patch("core.ai_fallback.time.sleep")
    def test_expired_budget_prevents_third_provider_request(self, sleep):
        budget = GenerationBudget(seconds=7)

        def respond(request):
            if len(self.requests) == 2:
                budget.deadline = time.monotonic() - 1
            return self.overloaded()

        client = self.make_client(respond)
        with generation_budget(budget), self.assertRaises(GenerationTimedOut):
            call_with_model_fallback(
                client.interactions.create, primary_model=PRIMARY,
                fallback_model=CONFIGURED_FALLBACK, input="offline fixture",
            )
        self.assertEqual(self.models_requested(), [PRIMARY, CONFIGURED_FALLBACK])
        sleep.assert_not_called()
