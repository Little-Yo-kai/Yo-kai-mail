from unittest.mock import patch

from django.test import SimpleTestCase

from assets.services.ssrf import normalize_public_asset_url

from .normalizers import build_website_snapshot


class WebsiteAssetURLTests(SimpleTestCase):
    @patch("socket.getaddrinfo", side_effect=AssertionError("No network during normalization"))
    def test_resolves_and_deduplicates_assets_against_redirected_page(self, dns):
        snapshot = build_website_snapshot("https://example.com/start", {
            "metadata": {
                "sourceURL": "https://www.example.com/shop/product/",
                "favicon": "/favicon.ico",
                "og:image": "../hero image.jpg?size=large&variant=blue",
            },
            "images": [
                "../hero image.jpg?size=large&variant=blue",
                "https://www.example.com/shop/hero%20image.jpg?size=large&variant=blue",
                "//cdn.example.com/detail.png",
                "/collection.png",
            ],
            "branding": {
                "logo": "data:image/svg+xml,<svg/>",
                "images": {"logo": "/logo.svg"},
            },
        })

        self.assertEqual(snapshot["source"]["resolved_url"], "https://www.example.com/shop/product/")
        self.assertEqual(snapshot["assets"], {
            "images": [
                "https://www.example.com/shop/hero%20image.jpg?size=large&variant=blue",
                "https://cdn.example.com/detail.png",
                "https://www.example.com/collection.png",
            ],
            "logo_candidate": "https://www.example.com/logo.svg",
            "favicon": "https://www.example.com/favicon.ico",
            "og_image": "https://www.example.com/shop/hero%20image.jpg?size=large&variant=blue",
        })
        dns.assert_not_called()

    def test_discards_unsafe_image_candidates_without_hiding_other_evidence(self):
        snapshot = build_website_snapshot("https://example.com/product", {
            "markdown": "Observed product copy",
            "metadata": {"og_image": "http://127.0.0.1/logo.jpg"},
            "images": [
                "javascript:alert(1)", "data:image/png;base64,AA", "file:///secret",
                "https://user:password@example.com/image.png", "https://localhost./a.png",
                "http://169.254.169.254/latest", "https://[::1]/a.png",
                "https://127.1/a.png", "https://0177.0.0.1/a.png", "https://0x7f.0.0.1/a.png",
                "https://example.com:invalid/a.png", "https://[bad/a.png",
                "https://example.com/\nimage.png", "//server.local/a.png", None,
            ],
        })
        self.assertEqual(snapshot["assets"]["images"], [])
        self.assertIsNone(snapshot["assets"]["og_image"])
        self.assertEqual(snapshot["content"]["markdown"], "Observed product copy")

    def test_invalid_provider_base_uses_requested_page_for_relative_assets(self):
        snapshot = build_website_snapshot("https://example.com/shop/item", {
            "metadata": {"source_url": "http://localhost/internal"},
            "images": ["photo.png"],
        })
        self.assertEqual(snapshot["assets"]["images"], ["https://example.com/shop/photo.png"])

    def test_normalizer_preserves_https_and_legacy_http_without_network(self):
        self.assertEqual(normalize_public_asset_url("HTTPS://CDN.EXAMPLE.COM/a.png"), "https://cdn.example.com/a.png")
        self.assertEqual(normalize_public_asset_url("http://cdn.example.com/a.png"), "http://cdn.example.com/a.png")
        self.assertIsNone(normalize_public_asset_url("https://example.com\\@localhost/a.png"))
