from unittest.mock import Mock

from core.ai_fallback import call_with_model_fallback
from django.test import TestCase
from django.urls import reverse


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
