"""Real runtime checks enabled in CI after installing MJML and Chromium."""

import base64
import os
from unittest import skipUnless

from campaigns.test_integrations import sample_brand_profile, sample_email_design
from django.test import SimpleTestCase

from .compiler import compile_mjml_to_html
from .renderer import render_email_to_mjml
from .screenshot import capture_email_screenshot


class EmailRuntimeSmokeTests(SimpleTestCase):
    def render(self):
        rendered = render_email_to_mjml(
            brand_profile=sample_brand_profile(),
            email_design=sample_email_design(),
            asset_inventory=[],
        )
        compiled = compile_mjml_to_html(rendered["mjml"])
        self.assertIn("A campaign", compiled["html"])
        self.assertEqual(compiled["compiler_errors"], [])
        return compiled["html"]

    @skipUnless(
        os.environ.get("EMAIL_RUNTIME_SMOKE") == "1",
        "Enable EMAIL_RUNTIME_SMOKE after npm ci --prefix mjml_runtime",
    )
    def test_real_mjml_compiler(self):
        self.render()

    @skipUnless(
        os.environ.get("EMAIL_BROWSER_SMOKE") == "1",
        "Enable EMAIL_BROWSER_SMOKE after playwright install chromium",
    )
    def test_real_desktop_and_mobile_screenshots(self):
        html = self.render()
        for width in (760, 375):
            with self.subTest(width=width):
                screenshot = capture_email_screenshot(
                    html, asset_urls=[], viewport_width=width
                )
                self.assertEqual(screenshot["width"], width)
                self.assertGreater(screenshot["height"], 0)
                self.assertTrue(
                    base64.b64decode(screenshot["image_base64"]).startswith(b"\x89PNG")
                )
                self.assertEqual(screenshot["image_diagnostics"]["broken"], [])
