from unittest.mock import patch

from django.test import SimpleTestCase

from .preview import build_preview_html


class PreviewRuntimeTests(SimpleTestCase):
    @patch("demo_flow.preview.Thread")
    @patch("demo_flow.preview.cleanup_expired_email_assets")
    @patch("demo_flow.preview.get_or_cache_remote_image")
    def test_email_without_matching_images_skips_background_and_cache_work(self, cache, cleanup, thread):
        for document, inventory in (
            ("<p>Text only email</p>", [{"url": "https://example.com/a.png"}]),
            ('<img src="https://example.com/other.png">', [{"url": "https://example.com/a.png"}]),
            ('<img src="https://example.com/a.png">', []),
        ):
            with self.subTest(document=document):
                self.assertEqual(build_preview_html(
                    html_document=document, asset_inventory=inventory,
                ), (document, [], []))
        cache.assert_not_called()
        cleanup.assert_not_called()
        thread.assert_not_called()
