import base64
import io
import re
import tempfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from PIL import Image

from demo_flow.preview import build_preview_html
from email_assets.html import image_sources
from email_assets.tests import image_bytes
from email_delivery.services.resend import ResendEmailService

from .compiler import compile_mjml_to_html
from .renderer import render_email_to_mjml
from .tests import sample_brand_profile, sample_email_design

SELECTED_URL = "https://cdn.example.com/selected.png?a=1&b=2"
OTHER_URL = "https://cdn.example.com/other.png"
LAYOUTS = ("full_width", "centered", "split_image_left", "split_image_right")


def inventory():
    return [
        {"asset_id": "unsafe", "kind": "product", "url": "data:image/png;base64,AAAA", "source": "request"},
        {"asset_id": "selected", "kind": "product", "url": SELECTED_URL, "source": "request"},
        {"asset_id": "other", "kind": "product", "url": OTHER_URL, "source": "request"},
    ]


class SelectedImageRendererTests(SimpleTestCase):
    def test_each_layout_uses_first_usable_selected_id_in_order(self):
        for layout in LAYOUTS:
            for leading_id in ("missing", "unsafe"):
                with self.subTest(layout=layout, leading_id=leading_id):
                    design = sample_email_design()
                    design["sections"][0].update(layout=layout, asset_ids=[leading_id, "selected", "other"])
                    rendered = render_email_to_mjml(
                        brand_profile=sample_brand_profile(), email_design=design,
                        asset_inventory=inventory(),
                    )
                    self.assertIn(SELECTED_URL.replace("&", "&amp;"), rendered["mjml"])
                    self.assertNotIn(OTHER_URL, rendered["mjml"])
                    self.assertNotIn("data:image", rendered["mjml"])

    def test_missing_or_unsafe_selections_do_not_insert_an_unselected_image(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                design = sample_email_design()
                design["sections"][0].update(layout=layout, asset_ids=["missing", "unsafe"])
                rendered = render_email_to_mjml(
                    brand_profile=sample_brand_profile(), email_design=design,
                    asset_inventory=inventory(),
                )
                self.assertNotIn("<mj-image", rendered["mjml"])
                self.assertIn("New Expression", rendered["mjml"])

    def test_valid_first_selection_keeps_priority_over_later_valid_images(self):
        design = sample_email_design()
        design["sections"][0]["asset_ids"] = ["other", "selected"]
        rendered = render_email_to_mjml(
            brand_profile=sample_brand_profile(), email_design=design,
            asset_inventory=inventory(),
        )
        self.assertIn(OTHER_URL, rendered["mjml"])
        self.assertNotIn(SELECTED_URL.replace("&", "&amp;"), rendered["mjml"])


@override_settings(
    RESEND_API_KEY="offline-image-fixture",
    RESEND_FROM_EMAIL="Example <sender@example.test>",
    MJML_COMPILE_CACHE_TTL_SECONDS=0,
)
class SameDesignImagePipelineTests(SimpleTestCase):
    def test_selected_image_survives_real_compilation_preview_and_send_mime(self):
        design = sample_email_design()
        design["sections"][0].update(
            layout="split_image_right", asset_ids=["unsafe", "selected"],
            headline="Selected image proof",
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            self.settings(EMAIL_ASSET_CACHE_DIR=directory),
            patch("email_assets.temp_cache._fetch_public_image", return_value=(
                image_bytes(size=(160, 80)), "image/png", SELECTED_URL,
            )) as fetch,
            patch("email_delivery.services.resend.resend.Emails.send", return_value={"id": "offline-only"}) as send,
        ):
            rendered = render_email_to_mjml(
                brand_profile=sample_brand_profile(), email_design=design,
                asset_inventory=inventory(),
            )
            compiled = compile_mjml_to_html(rendered["mjml"])
            self.assertEqual(compiled["compiler_errors"], [])
            self.assertEqual(image_sources(compiled["html"]), {SELECTED_URL})
            preview, diagnostics, cached = build_preview_html(
                html_document=compiled["html"], asset_inventory=inventory(),
            )
            preview_src, = image_sources(preview)
            self.assertTrue(preview_src.startswith("data:image/png;base64,"))
            preview_bytes = base64.b64decode(preview_src.split(",", 1)[1], validate=True)
            self.assertEqual(diagnostics[0]["status"], "embedded")

            ResendEmailService().send_test_email(
                to="recipient@example.test", subject=design["subject"],
                html=compiled["html"], cached_assets=cached,
            )
            fetch.assert_called_once()
            self.assertEqual(fetch.call_args.args, (SELECTED_URL,))
            send.assert_called_once()
            params = send.call_args.args[0]
            attachment, = params["attachments"]
            self.assertEqual(attachment["content_type"], "image/png")
            self.assertEqual(base64.b64decode(attachment["content"], validate=True), preview_bytes)
            self.assertEqual(image_sources(params["html"]), {f"cid:{attachment['content_id']}"})
            self.assertIn("Selected image proof", params["text"])
            self.assertIn("Discover (https://example.com/product)", re.sub(r"\s+", " ", params["text"]))

            # Round-trip the real SDK payload through MIME entirely in memory.
            message = EmailMessage()
            message.set_content(params["text"])
            message.add_alternative(params["html"], subtype="html")
            message.get_payload()[-1].add_related(
                base64.b64decode(attachment["content"], validate=True),
                maintype="image", subtype="png", disposition="inline",
                cid=f"<{attachment['content_id']}>", filename=attachment["filename"],
            )
            parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
            image_part = next(part for part in parsed.walk() if part.get_content_type() == "image/png")
            self.assertEqual(image_part.get_payload(decode=True), preview_bytes)
            self.assertEqual(image_part.get_content_disposition(), "inline")
            self.assertIn(image_part["Content-ID"].strip("<>"), parsed.get_body(preferencelist=("html",)).get_content())
            self.assertIn("Selected image proof", parsed.get_body(preferencelist=("plain",)).get_content())
            with Image.open(io.BytesIO(image_part.get_payload(decode=True))) as image:
                self.assertEqual(image.size, (160, 80))
