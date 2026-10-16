import json
import time
from unittest.mock import Mock, patch

import httpx
import requests
from django.test import SimpleTestCase, override_settings
from firecrawl import FirecrawlError
from google import genai
from google.genai._gaos.lib.compat_errors import InternalServerError

from core.ai_fallback import call_with_model_fallback
from core.gemini_client import create_gemini_client
from core.generation_budget import (
    GenerationBudget,
    GenerationTimedOut,
    generation_budget,
)
from website_intelligence.services.firecrawl import FirecrawlService


class ProviderDeadlineTests(SimpleTestCase):
    @patch("time.sleep")
    def test_real_sdk_does_not_hide_retry_after_sleeps_or_extra_attempts(self, sleep):
        requests_seen = []

        def overloaded(request):
            requests_seen.append(request)
            return httpx.Response(
                503,
                headers={"Retry-After": "1800"},
                json={
                    "error": {
                        "code": 503,
                        "message": "high demand",
                        "status": "UNAVAILABLE",
                    }
                },
            )

        def factory(**kwargs):
            return genai.Client(
                **{
                    **kwargs,
                    "http_options": {
                        **kwargs["http_options"],
                        "httpx_client": httpx.Client(
                            transport=httpx.MockTransport(overloaded), trust_env=False
                        ),
                        "async_client_args": {"trust_env": False},
                    },
                }
            )

        client = create_gemini_client(api_key="test-key", client_factory=factory)
        self.addCleanup(client.close)
        with (
            generation_budget(GenerationBudget(seconds=7)),
            self.assertRaises(InternalServerError),
        ):
            call_with_model_fallback(
                client.interactions.create,
                primary_model="primary",
                fallback_model="fallback",
                input="hello",
            )

        self.assertEqual(
            [json.loads(r.content)["model"] for r in requests_seen],
            ["primary", "fallback", "fallback"],
        )
        for request in requests_seen:
            self.assertGreater(request.extensions["timeout"]["read"], 0)
            self.assertLessEqual(request.extensions["timeout"]["read"], 7)
        sleep.assert_called_once_with(0.5)

    def test_deadline_exhaustion_prevents_fallback_call(self):
        budget = GenerationBudget(seconds=10)

        def overload(**kwargs):
            budget.deadline = time.monotonic() - 1
            raise RuntimeError("HTTP 503 high demand")

        create = Mock(side_effect=overload)
        with generation_budget(budget), self.assertRaises(GenerationTimedOut):
            call_with_model_fallback(
                create, primary_model="primary", fallback_model="fallback"
            )
        self.assertEqual(create.call_count, 1)

    @override_settings(
        FIRECRAWL_API_KEY="test-key", FIRECRAWL_REQUEST_TIMEOUT_SECONDS=40
    )
    @patch("requests.post")
    def test_real_firecrawl_sdk_gets_http_and_scrape_deadlines(self, post):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"success":true,"data":{"markdown":"Example"}}'
        post.return_value = response
        with generation_budget(GenerationBudget(seconds=5)):
            result = FirecrawlService().scrape("https://example.com")
        self.assertEqual(result["markdown"], "Example")
        self.assertEqual(post.call_count, 1)
        self.assertLessEqual(post.call_args.kwargs["timeout"], 5)
        self.assertLessEqual(post.call_args.kwargs["json"]["timeout"], 5000)

    @override_settings(FIRECRAWL_API_KEY="test-key")
    @patch("time.sleep")
    @patch("requests.post")
    def test_firecrawl_processing_timeout_never_enters_twenty_minute_resume(
        self, post, sleep
    ):
        response = requests.Response()
        response.status_code = 408
        response.headers["Retry-After"] = "600"
        response._content = json.dumps(
            {
                "success": False,
                "code": "SCRAPE_TIMEOUT",
                "error": "Scrape timed out",
                "details": {"state": "processing_continues"},
            }
        ).encode()
        post.return_value = response
        with self.assertRaises(FirecrawlError):
            FirecrawlService().scrape("https://example.com")
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()
