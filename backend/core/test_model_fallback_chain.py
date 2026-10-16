import time
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from .ai_fallback import call_with_model_fallback
from .generation_budget import GenerationBudget, GenerationTimedOut, generation_budget


@override_settings(GEMINI_ADDITIONAL_FALLBACK_MODELS=["third-model"])
class ModelCapacityChainTests(SimpleTestCase):
    def call(self, create):
        return call_with_model_fallback(
            create,
            primary_model="primary",
            fallback_model="fallback",
            input="private prompt",
        )

    @patch("core.ai_fallback.time.sleep")
    def test_third_model_recovers_without_retrying_overloaded_fallback(self, sleep):
        create = Mock(
            side_effect=[
                RuntimeError("HTTP 503"),
                RuntimeError("HTTP 503"),
                "recovered",
            ]
        )
        with self.assertLogs("core.ai_fallback", level="WARNING") as logs:
            self.assertEqual(self.call(create), "recovered")
        self.assertEqual(
            [call.kwargs["model"] for call in create.call_args_list],
            ["primary", "fallback", "third-model"],
        )
        sleep.assert_not_called()
        self.assertNotIn("private prompt", " ".join(logs.output))
        self.assertIn("next_model=third-model", " ".join(logs.output))

    @override_settings(
        GEMINI_ADDITIONAL_FALLBACK_MODELS=[
            "primary",
            " fallback ",
            "third-model",
            "fourth-model",
        ]
    )
    @patch("core.ai_fallback.time.sleep")
    def test_all_busy_stops_after_three_unique_models(self, sleep):
        create = Mock(side_effect=RuntimeError("HTTP 503"))
        with self.assertRaisesRegex(RuntimeError, "503"):
            self.call(create)
        self.assertEqual(
            [call.kwargs["model"] for call in create.call_args_list],
            ["primary", "fallback", "third-model"],
        )
        sleep.assert_not_called()

    @patch("core.ai_fallback.time.sleep")
    def test_rate_limits_try_distinct_models_but_never_retry_same_model(self, sleep):
        create = Mock(side_effect=RuntimeError("HTTP 429 rate limit exceeded"))
        with self.assertRaisesRegex(RuntimeError, "429"):
            self.call(create)
        self.assertEqual(create.call_count, 3)
        sleep.assert_not_called()

    def test_explicit_nontransient_status_wins_over_capacity_words(self):
        for status in (400, 401, 403, 404, 500):
            with self.subTest(status=status):
                error = RuntimeError(f"HTTP {status}: high demand and rate limit")
                create = Mock(side_effect=error)
                with self.assertRaises(RuntimeError):
                    self.call(create)
                create.assert_called_once()

    def test_deadline_expiring_on_second_failure_prevents_third_call(self):
        budget = GenerationBudget(seconds=10)
        calls = []

        def overloaded(**kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 2:
                budget.deadline = time.monotonic() - 1
            raise RuntimeError("HTTP 503")

        with generation_budget(budget), self.assertRaises(GenerationTimedOut):
            self.call(overloaded)
        self.assertEqual(calls, ["primary", "fallback"])

    @override_settings(GEMINI_ADDITIONAL_FALLBACK_MODELS=[])
    def test_final_retry_sleep_respects_remaining_deadline(self):
        budget = GenerationBudget(seconds=10)
        create = Mock()

        def overloaded(**kwargs):
            if create.call_count == 2:
                budget.deadline = time.monotonic() + 0.05
            raise RuntimeError("HTTP 503")

        def exhaust_budget(delay):
            self.assertGreater(delay, 0)
            self.assertLess(delay, 0.05)
            budget.deadline = time.monotonic() - 1

        create.side_effect = overloaded
        with (
            generation_budget(budget),
            patch("core.ai_fallback.time.sleep", side_effect=exhaust_budget) as sleep,
            self.assertRaises(GenerationTimedOut),
        ):
            self.call(create)
        self.assertEqual(create.call_count, 2)
        sleep.assert_called_once()
