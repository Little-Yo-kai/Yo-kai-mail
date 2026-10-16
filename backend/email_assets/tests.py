import io
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.test import SimpleTestCase
from PIL import Image

from .html import image_sources, replace_image_sources
from .temp_cache import EmailAssetCacheError, cache_image_bytes, read_cached_email_asset


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
