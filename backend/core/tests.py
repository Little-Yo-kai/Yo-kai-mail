from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from core.ai_fallback import (
    call_with_model_fallback,
    is_temporary_unavailability_error,
)
from core.provider_errors import is_provider_rate_limited


class ApiSchemaTests(TestCase):
    def test_schema_endpoint_renders(self):
        response = self.client.get(reverse("schema"))
        self.assertEqual(response.status_code, 200)



class AiFallbackTests(TestCase):
    def test_rate_limit_retries_with_fallback_model(self):
        create = Mock()
        create.side_effect = [
            RuntimeError(
                "Error code: 429 - rate limit exceeded / too_many_requests"
            ),
            "ok",
        ]

        result = call_with_model_fallback(
            create,
            primary_model="primary-model",
            fallback_model="fallback-model",
            input="hello",
        )

        self.assertEqual(result, "ok")
        self.assertEqual(create.call_count, 2)
        self.assertEqual(
            create.call_args_list[0].kwargs["model"],
            "primary-model",
        )
        self.assertEqual(
            create.call_args_list[1].kwargs["model"],
            "fallback-model",
        )

    def test_non_rate_limit_error_does_not_fallback(self):
        create = Mock()
        create.side_effect = RuntimeError("authentication failed")

        with self.assertRaises(RuntimeError):
            call_with_model_fallback(
                create,
                primary_model="primary-model",
                fallback_model="fallback-model",
                input="hello",
            )

        self.assertEqual(create.call_count, 1)

    def test_provider_error_classification_keeps_non_rate_limit_failures(self):
        self.assertFalse(
            is_provider_rate_limited(
                RuntimeError("authentication failed: invalid key")
            )
        )
        self.assertTrue(
            is_provider_rate_limited(
                RuntimeError("Error code: 429 - too_many_requests")
            )
        )


    def test_gemini_503_high_demand_uses_fallback_model(self):
        create = Mock(side_effect=[
            RuntimeError(
                "Error code: 503 - {'error': {'message': "
                "'gemini-3.8-flash is currently experiencing high demand', "
                "'code': 'service_unavailable'}}"
            ),
            "recovered",
        ])

        result = call_with_model_fallback(
            create,
            primary_model="gemini-3.8-flash",
            fallback_model="gemini-3.1-flash-lite",
            input="example",
        )

        self.assertEqual(result, "recovered")
        self.assertEqual(
            [call.kwargs["model"] for call in create.call_args_list],
            ["gemini-3.8-flash", "gemini-3.1-flash-lite"],
        )

    @patch("core.ai_fallback.time.sleep")
    def test_final_model_gets_one_bounded_retry_for_503(self, sleep):
        create = Mock(side_effect=[
            RuntimeError("Error code: 503 - service_unavailable"),
            RuntimeError("Error code: 503 - service_unavailable"),
            "recovered",
        ])

        result = call_with_model_fallback(
            create,
            primary_model="primary-model",
            fallback_model="fallback-model",
        )

        self.assertEqual(result, "recovered")
        self.assertEqual(
            [call.kwargs["model"] for call in create.call_args_list],
            ["primary-model", "fallback-model", "fallback-model"],
        )
        sleep.assert_called_once_with(0.5)

    @patch("core.ai_fallback.time.sleep")
    def test_both_models_overloaded_fails_after_bounded_attempts(self, sleep):
        create = Mock(
            side_effect=RuntimeError(
                "Error code: 503 - service_unavailable"
            )
        )

        with self.assertRaisesRegex(RuntimeError, "503"):
            call_with_model_fallback(
                create,
                primary_model="primary-model",
                fallback_model="fallback-model",
            )

        self.assertEqual(create.call_count, 3)
        sleep.assert_called_once_with(0.5)

    @patch("core.ai_fallback.time.sleep")
    def test_auth_and_invalid_request_do_not_retry_or_fallback(self, sleep):
        for message in (
            "Error code: 401 - invalid API key",
            "Error code: 400 - invalid response schema",
        ):
            with self.subTest(message=message):
                create = Mock(side_effect=RuntimeError(message))
                with self.assertRaises(RuntimeError):
                    call_with_model_fallback(
                        create,
                        primary_model="primary",
                        fallback_model="fallback",
                    )
                self.assertEqual(create.call_count, 1)
        sleep.assert_not_called()

    @patch("core.ai_fallback.time.sleep")
    def test_same_model_configured_twice_retries_only_once(self, sleep):
        create = Mock(side_effect=[
            RuntimeError("Error code: 503 - high demand"),
            "recovered",
        ])

        result = call_with_model_fallback(
            create,
            primary_model=" same-model ",
            fallback_model="same-model",
        )

        self.assertEqual(result, "recovered")
        self.assertEqual(create.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_classifies_structured_503_and_not_regular_500(self):
        service_unavailable = RuntimeError("temporary overload")
        service_unavailable.status_code = 503

        self.assertTrue(
            is_temporary_unavailability_error(service_unavailable)
        )
        self.assertFalse(
            is_temporary_unavailability_error(
                RuntimeError("Error code: 500 - internal failure")
            )
        )
