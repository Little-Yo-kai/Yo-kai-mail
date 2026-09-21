from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .services.resend import ResendEmailService


class ResendEmailServiceTests(APITestCase):
    @override_settings(
        RESEND_API_KEY="re_test",
        RESEND_FROM_EMAIL="Yo-kai Mail <onboarding@resend.dev>",
    )
    @patch("email_delivery.services.resend.resend.Emails.send")
    def test_send_uses_final_html_and_idempotency(self, send_mock):
        send_mock.return_value = {"id": "email_123"}

        result = ResendEmailService().send_test_email(
            to="recipient@example.com",
            subject="Generated campaign",
            html="<html><body>Hello</body></html>",
        )

        self.assertEqual(result["email_id"], "email_123")
        self.assertEqual(result["provider"], "resend")

        params, options = send_mock.call_args.args
        self.assertEqual(
            params["from"],
            "Yo-kai Mail <onboarding@resend.dev>",
        )
        self.assertEqual(params["to"], ["recipient@example.com"])
        self.assertEqual(params["subject"], "Generated campaign")
        self.assertEqual(
            params["html"],
            "<html><body>Hello</body></html>",
        )
        self.assertTrue(
            options["idempotency_key"].startswith("yo-kai-demo/")
        )

    @override_settings(
        RESEND_API_KEY="re_test",
        RESEND_FROM_EMAIL="Yo-kai Mail <onboarding@resend.dev>",
    )
    @patch("email_delivery.services.resend.resend.Emails.send")
    def test_same_payload_gets_same_default_idempotency_key(
        self,
        send_mock,
    ):
        send_mock.return_value = {"id": "email_123"}
        service = ResendEmailService()

        service.send_test_email(
            to="recipient@example.com",
            subject="Generated campaign",
            html="<strong>Hello</strong>",
        )
        first_options = send_mock.call_args.args[1]

        service.send_test_email(
            to="recipient@example.com",
            subject="Generated campaign",
            html="<strong>Hello</strong>",
        )
        second_options = send_mock.call_args.args[1]

        self.assertEqual(
            first_options["idempotency_key"],
            second_options["idempotency_key"],
        )


class TestEmailSendApiTests(APITestCase):
    @override_settings(RESEND_TEST_SEND_ENABLED=False)
    def test_test_send_can_be_disabled(self):
        response = self.client.post(
            reverse("email-delivery-send-test"),
            {
                "to": "recipient@example.com",
                "subject": "Hello",
                "html": "<strong>Hello</strong>",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    @override_settings(RESEND_TEST_SEND_ENABLED=True)
    @patch("email_delivery.views.ResendEmailService")
    def test_test_send_endpoint_returns_provider_id(self, service_class):
        service_class.return_value.send_test_email.return_value = {
            "email_id": "email_123",
            "provider": "resend",
            "to": "recipient@example.com",
            "from": "Yo-kai Mail <onboarding@resend.dev>",
            "idempotency_key": "yo-kai-demo/test",
        }

        response = self.client.post(
            reverse("email-delivery-send-test"),
            {
                "to": "recipient@example.com",
                "subject": "Hello",
                "html": "<strong>Hello</strong>",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["email_id"],
            "email_123",
        )
