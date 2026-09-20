from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .service import _default_campaign_brief


class DemoCampaignDefaultsTests(APITestCase):
    def test_url_only_campaign_has_safe_defaults(self):
        brief = _default_campaign_brief(
            url="https://example.com",
            brand_profile={
                "identity": {
                    "name": "Example",
                }
            },
        )

        self.assertEqual(brief["campaign_type"], "newsletter")
        self.assertEqual(brief["goal"], "brand_awareness")
        self.assertEqual(
            brief["destination_url"],
            "https://example.com",
        )
        self.assertEqual(brief["offer"]["type"], "none")
        self.assertIsNone(brief["product"])


class DemoGenerateApiTests(APITestCase):
    @patch("demo_flow.views.generate_phase1_demo")
    def test_url_only_demo_generation(self, generate_mock):
        generate_mock.return_value = {
            "mode": "automatic_reference",
            "email_design": {
                "subject": "Hello",
                "preheader": "Preview",
                "sections": [],
            },
            "render": {
                "html": "<!doctype html><html></html>",
                "mjml": "<mjml></mjml>",
            },
        }

        response = self.client.post(
            reverse("phase1-demo-generate"),
            {
                "url": "https://example.com",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["mode"],
            "automatic_reference",
        )
        generate_mock.assert_called_once()
        self.assertIsNone(
            generate_mock.call_args.kwargs["reference_image"]
        )

    @patch("demo_flow.views.generate_phase1_demo")
    def test_uploaded_reference_is_forwarded(self, generate_mock):
        generate_mock.return_value = {
            "mode": "uploaded_reference",
            "email_design": {
                "subject": "Hello",
                "preheader": "Preview",
                "sections": [],
            },
            "render": {
                "html": "<!doctype html><html></html>",
                "mjml": "<mjml></mjml>",
            },
        }

        image = SimpleUploadedFile(
            "reference.png",
            b"fake-image-bytes",
            content_type="image/png",
        )

        response = self.client.post(
            reverse("phase1-demo-generate"),
            {
                "url": "https://example.com",
                "reference_image": image,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["mode"],
            "uploaded_reference",
        )
        self.assertIsNotNone(
            generate_mock.call_args.kwargs["reference_image"]
        )
