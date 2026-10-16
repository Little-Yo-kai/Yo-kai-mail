import base64
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from email_assets.temp_cache import EmailAssetCacheError
from email_assets.tests import image_bytes
from email_delivery.services.resend import ResendDeliveryError, ResendEmailService
from email_rendering.tests import sample_brand_profile, sample_email_design

from .service import _default_campaign_brief


class ProductCampaignTests(APITestCase):
    def test_product_page_evidence_reaches_the_campaign_brief(self):
        product = {
            "name": "All In BB",
            "description": "Monogram Pearly coated canvas",
            "url": "https://example.com/item",
        }
        brief = _default_campaign_brief(
            url=product["url"],
            brand_profile=sample_brand_profile(),
            snapshot={"product": product},
        )
        self.assertEqual(brief["product"], product)
        self.assertEqual(brief["goal"], "product_discovery")
        self.assertIn("Do not imply a new launch", brief["additional_instructions"])


@override_settings(RESEND_API_KEY="re_test", RESEND_FROM_EMAIL="preview@example.com")
class ImageEditingDeliveryTests(APITestCase):
    @patch(
        "demo_flow.editing.build_preview_html",
        return_value=("<html>Preview</html>", [], []),
    )
    @patch("demo_flow.editing.compile_mjml_to_html")
    def test_copy_edits_return_plain_text_and_quality_warnings(
        self, compile_mock, preview_mock
    ):
        design = sample_email_design()
        design["subject"] = "A subject written by the user"
        design["preheader"] = "A preview written by the user"
        design["sections"][0]["headline"] = "Your <edited> headline"
        compile_mock.return_value = {
            "html": "<html>Edited email</html>",
            "text": "Edited email",
            "compiler_errors": [],
        }
        response = self.client.post(
            reverse("phase1-demo-render"),
            {
                "brand_profile": sample_brand_profile(),
                "email_design": design,
                "asset_inventory": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        rendered = response.data["data"]
        self.assertEqual(rendered["text"], "Edited email")
        self.assertIn("Your &lt;edited&gt; headline", rendered["mjml"])
        self.assertIn(
            "missing-footer", [warning["code"] for warning in rendered["warnings"]]
        )
        self.assertIn("A subject written by the user", rendered["mjml"])

    @patch("resend.default_http_client.request")
    @patch("demo_flow.editing.compile_mjml_to_html")
    def test_upload_edit_preview_and_actual_sdk_request_share_valid_image_bytes(
        self, compile_mock, request_mock
    ):
        request_mock.return_value = (
            '{"id":"email_123"}',
            200,
            {"content-type": "application/json"},
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            self.settings(EMAIL_ASSET_CACHE_DIR=directory),
        ):
            response = self.client.post(
                reverse("phase1-demo-image-upload"),
                {
                    "image": SimpleUploadedFile(
                        "new.png", image_bytes(), content_type="image/png"
                    )
                },
                format="multipart",
            )
            self.assertEqual(response.status_code, 200)
            asset = response.data["data"]["asset"]
            self.assertNotIn("{cache_key}", asset["url"])
            image_response = self.client.get(asset["url"])
            self.assertEqual(image_response.status_code, 200)
            design = sample_email_design()
            design["sections"][0]["asset_ids"] = [asset["asset_id"]]
            design["sections"][0]["layout"] = "split_image_right"
            compile_mock.return_value = {
                "html": f'<html><img src="{asset["url"]}"></html>',
                "compiler_errors": [],
            }
            response = self.client.post(
                reverse("phase1-demo-render"),
                {
                    "brand_profile": sample_brand_profile(),
                    "email_design": design,
                    "asset_inventory": [asset],
                },
                format="json",
            )
            self.assertEqual(response.status_code, 200)
            rendered = response.data["data"]
            self.assertTrue(rendered["delivery_ready"])
            self.assertIn("data:image/png;base64,", rendered["preview_html"])
            self.assertIn('direction="rtl"', rendered["mjml"])

            result = ResendEmailService().send_test_email(
                to="preview@example.com",
                subject="Image preview",
                html=rendered["html"],
                cached_assets=rendered["cached_assets"],
            )
            payload = request_mock.call_args.kwargs["json"]
            attached = payload["attachments"][0]
            self.assertEqual(
                base64.b64decode(attached["content"]), image_response.content
            )
            self.assertIn(f"cid:{attached['content_id']}", payload["html"])
            self.assertNotIn("http://testserver", payload["html"])
            self.assertEqual(result["inline_asset_bytes"], len(image_response.content))

    @patch(
        "email_delivery.services.resend.get_or_cache_remote_image",
        side_effect=EmailAssetCacheError("CDN refused download"),
    )
    @patch("resend.default_http_client.request")
    def test_missing_image_is_reported_before_a_message_is_sent(
        self, request_mock, fetch_mock
    ):
        with self.assertRaises(ResendDeliveryError):
            ResendEmailService().send_test_email(
                to="preview@example.com",
                subject="Broken image",
                html="<img src='https://example.com/blocked.jpg'>",
            )
        request_mock.assert_not_called()

    def test_upload_rejects_non_image_content(self):
        response = self.client.post(
            reverse("phase1-demo-image-upload"),
            {
                "image": SimpleUploadedFile(
                    "fake.png", b"not a PNG", content_type="image/png"
                ),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
