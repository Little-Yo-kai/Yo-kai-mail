import io
import tempfile
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from PIL import Image

from assets.services.ssrf import SSRFBlockedError, assert_safe_url

from .html import image_sources, replace_image_sources
from .temp_cache import (
    EmailAssetCacheError,
    _detect_asset_mime,
    _fetch_public_image,
    cache_image_bytes,
    get_or_cache_remote_image,
    read_cached_email_asset,
)


def image_bytes(*, size=(32, 32), format="PNG", mode="RGBA"):
    output = io.BytesIO()
    Image.new(mode, size, "#cebb99").save(output, format=format)
    return output.getvalue()


class EmailAssetTests(SimpleTestCase):
    def test_concurrent_writers_preserve_one_valid_image(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            self.settings(EMAIL_ASSET_CACHE_DIR=directory),
            ThreadPoolExecutor(max_workers=6) as pool,
        ):
            content = image_bytes(size=(600, 750))
            results = list(
                pool.map(
                    lambda _: cache_image_bytes(
                        content, source_url="https://example.com/shared.png"
                    ),
                    range(12),
                )
            )
            self.assertEqual(len({item.cache_key for item in results}), 1)
            self.assertEqual(
                read_cached_email_asset(results[0].cache_key).body, results[0].body
            )
            self.assertEqual(len(list(Path(directory).rglob("*"))), 5)

    def test_cache_validates_and_converts_webp_for_email_clients(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            self.settings(EMAIL_ASSET_CACHE_DIR=directory),
        ):
            cached = cache_image_bytes(
                image_bytes(size=(1800, 900), format="WEBP", mode="RGB"),
                source_url="https://example.com/product.webp",
            )
            self.assertEqual(cached.mime_type, "image/jpeg")
            with Image.open(io.BytesIO(cached.body)) as image:
                self.assertEqual(image.size, (1600, 800))

    def test_fake_images_and_tracking_pixels_are_rejected(self):
        for content in (b"<html>Access denied</html>", image_bytes(size=(1, 1))):
            with (
                self.subTest(content=content[:8]),
                self.assertRaises(EmailAssetCacheError),
            ):
                cache_image_bytes(content, source_url="https://example.com/fake.jpg")

    def test_image_replacement_handles_quotes_and_html_entities(self):
        document = (
            "<img SRC = 'https://example.com/a.jpg?a=1&amp;b=2'><a href='x'>Link</a>"
        )
        url = "https://example.com/a.jpg?a=1&b=2"
        self.assertEqual(image_sources(document), {url})
        self.assertIn(
            "SRC = 'cid:image-one'",
            replace_image_sources(document, {url: "cid:image-one"}),
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
        response.read1.side_effect = [body, b""]
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
        response.read1.side_effect = [b"12345"]
        build_opener.return_value.open.return_value = response
        with self.assertRaises(EmailAssetCacheError):
            _fetch_public_image("https://cdn.example.com/hero.png")
        response.read1.assert_called_once_with(5)
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
        self.assertEqual(second.body, first.body)
        with Image.open(io.BytesIO(second.body)) as image:
            self.assertEqual(image.size, (40, 20))
        self.assertEqual(first.cache_key, second.cache_key)
        fetch.assert_called_once()

    @patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))])
    def test_public_looking_hostname_still_requires_public_dns(self, dns):
        with self.assertRaises(SSRFBlockedError):
            assert_safe_url("https://cdn.example.com/hero.png")
