import io
import tempfile
import urllib.error
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from PIL import Image

from assets.services.ssrf import SSRFBlockedError, assert_safe_url

from .temp_cache import (
    EmailAssetCacheError,
    _detect_asset_mime,
    _fetch_public_image,
    get_or_cache_remote_image,
)


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (40, 20), (255, 0, 0)).save(output, format="PNG")
    return output.getvalue()


class TemporaryImageValidationTests(SimpleTestCase):
    def test_validates_image_bytes_and_accepted_content_types(self):
        body = png_bytes()
        self.assertEqual(_detect_asset_mime(body, "image/png; charset=binary"), "image/png")
        self.assertEqual(_detect_asset_mime(body, "application/octet-stream"), "image/png")
        self.assertEqual(_detect_asset_mime(body, None), "image/png")
        self.assertIsNone(_detect_asset_mime(body, "text/html"))
        self.assertIsNone(_detect_asset_mime(b"\x89PNG\r\n\x1a\ntruncated", "image/png"))
        self.assertIsNone(_detect_asset_mime(b"<html>not an image</html>", "image/png"))

    def test_accepts_svg_images_but_rejects_xml_and_active_or_external_content(self):
        self.assertEqual(_detect_asset_mime(b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>', "image/svg+xml"), "image/svg+xml")
        for body in (
            b'<?xml version="1.0"?><html/>', b"<svg><script>alert(1)</script></svg>",
            b'<svg onload="alert(1)"/>', b'<svg><image href="http://localhost/a"/></svg>',
            b'<svg><style>@import "https://example.com/a.css";</style></svg>',
            b'<svg style="fill:url(https://example.com/pattern)"/>',
            b'<!DOCTYPE svg [<!ENTITY x "expanded">]><svg>&x;</svg>',
            b"<svg>truncated",
        ):
            with self.subTest(body=body):
                self.assertIsNone(_detect_asset_mime(body, "image/svg+xml"))
        self.assertEqual(_detect_asset_mime(b'<svg><path fill="url(#gradient)"/></svg>', "image/svg+xml"), "image/svg+xml")

    @patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))])
    @patch("email_assets.temp_cache.urllib.request.build_opener")
    def test_fetch_preserves_original_image_bytes_and_closes_response(self, build_opener, dns):
        body = png_bytes()
        response = Mock(headers={"Content-Type": "image/png"})
        response.read.return_value = body
        build_opener.return_value.open.return_value = response
        actual, mime_type, resolved = _fetch_public_image("https://cdn.example.com/hero image.png")
        self.assertEqual((actual, mime_type, resolved), (body, "image/png", "https://cdn.example.com/hero%20image.png"))
        with Image.open(io.BytesIO(actual)) as image:
            self.assertEqual(image.size, (40, 20))
        response.close.assert_called_once()

    @patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))])
    @patch("email_assets.temp_cache.urllib.request.build_opener")
    def test_private_redirect_is_rejected_before_second_request(self, build_opener, dns):
        build_opener.return_value.open.side_effect = urllib.error.HTTPError(
            "https://cdn.example.com/hero.png", 302, "Redirect",
            {"Location": "http://169.254.169.254/latest"}, io.BytesIO(),
        )
        with self.assertRaises(EmailAssetCacheError):
            _fetch_public_image("https://cdn.example.com/hero.png")
        build_opener.return_value.open.assert_called_once()

    @override_settings(EMAIL_ASSET_MAX_IMAGE_BYTES=4)
    @patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))])
    @patch("email_assets.temp_cache.urllib.request.build_opener")
    def test_size_limit_still_closes_response(self, build_opener, dns):
        response = Mock(headers={"Content-Type": "image/png"})
        response.read.return_value = b"12345"
        build_opener.return_value.open.return_value = response
        with self.assertRaises(EmailAssetCacheError):
            _fetch_public_image("https://cdn.example.com/hero.png")
        response.read.assert_called_once_with(5)
        response.close.assert_called_once()

    @patch("email_assets.temp_cache._fetch_public_image")
    def test_cached_image_reuses_bytes_without_refetching(self, fetch):
        body = png_bytes()
        fetch.return_value = (body, "image/png", "https://cdn.example.com/hero.png")
        with (
            tempfile.TemporaryDirectory() as directory,
            self.settings(EMAIL_ASSET_CACHE_DIR=directory),
        ):
            first = get_or_cache_remote_image("https://example.com/hero.png")
            second = get_or_cache_remote_image("https://example.com/hero.png")
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.body, body)
        self.assertEqual(first.cache_key, second.cache_key)
        fetch.assert_called_once()

    @patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))])
    def test_public_looking_hostname_still_requires_public_dns(self, dns):
        with self.assertRaises(SSRFBlockedError):
            assert_safe_url("https://cdn.example.com/hero.png")
