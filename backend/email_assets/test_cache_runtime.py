import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import patch

from django.test import SimpleTestCase

from . import temp_cache
from .temp_cache import (
    EmailAssetCacheError,
    cache_image_bytes,
    cleanup_expired_email_assets,
    get_or_cache_remote_image,
    read_cached_email_asset,
)
from .tests import image_bytes


class ImageCacheRuntimeTests(SimpleTestCase):
    def test_concurrent_identical_misses_fetch_and_convert_once(self):
        ready = Barrier(4)
        fetching = Event()
        release = Event()
        body = image_bytes(size=(600, 300))

        def fetch(url, **kwargs):
            fetching.set()
            self.assertTrue(release.wait(2))
            return body, "image/png", url

        def get(_):
            ready.wait(timeout=2)
            return get_or_cache_remote_image("https://example.com/shared.png", timeout=2)

        with (
            tempfile.TemporaryDirectory() as directory,
            self.settings(EMAIL_ASSET_CACHE_DIR=directory),
            patch.object(temp_cache, "_fetch_public_image", side_effect=fetch) as fetched,
            patch.object(temp_cache, "cache_image_bytes", wraps=cache_image_bytes) as converted,
            ThreadPoolExecutor(max_workers=4) as pool,
        ):
            futures = [pool.submit(get, index) for index in range(4)]
            try:
                self.assertTrue(fetching.wait(2))
            finally:
                release.set()
            results = [future.result(timeout=2) for future in futures]
        self.assertEqual(fetched.call_count, 1)
        self.assertEqual(converted.call_count, 1)
        self.assertEqual(len({result.cache_key for result in results}), 1)
        self.assertEqual(sum(result.cache_hit for result in results), 3)

    def test_waiting_for_another_fetch_respects_callers_deadline(self):
        fetching = Event()
        release = Event()
        body = image_bytes()

        def fetch(url, **kwargs):
            fetching.set()
            self.assertTrue(release.wait(2))
            return body, "image/png", url

        with (
            tempfile.TemporaryDirectory() as directory,
            self.settings(EMAIL_ASSET_CACHE_DIR=directory),
            patch.object(temp_cache, "_fetch_public_image", side_effect=fetch) as fetched,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            first = pool.submit(get_or_cache_remote_image, "https://example.com/shared.png", timeout=2)
            try:
                self.assertTrue(fetching.wait(2))
                started = time.monotonic()
                with self.assertRaisesMessage(EmailAssetCacheError, "timed out"):
                    get_or_cache_remote_image("https://example.com/shared.png", timeout=0.02)
                self.assertLess(time.monotonic() - started, 0.5)
                fetched.assert_called_once()
            finally:
                release.set()
            first.result(timeout=2)

    def test_failed_fetch_does_not_block_a_following_retry(self):
        url = "https://example.com/retry.png"
        with (
            tempfile.TemporaryDirectory() as directory,
            self.settings(EMAIL_ASSET_CACHE_DIR=directory),
            patch.object(temp_cache, "_fetch_public_image", side_effect=[
                EmailAssetCacheError("Unavailable"), (image_bytes(), "image/png", url),
            ]) as fetched,
        ):
            with self.assertRaises(EmailAssetCacheError):
                get_or_cache_remote_image(url)
            self.assertTrue(get_or_cache_remote_image(url).body)
            self.assertEqual(fetched.call_count, 2)

    def test_expiry_sweeps_are_throttled_and_resume_after_interval(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            self.settings(EMAIL_ASSET_CACHE_DIR=directory),
            patch.object(temp_cache, "_last_cleanup", None),
            patch.object(temp_cache, "_remove_expired_email_assets") as sweep,
            patch.object(temp_cache.time, "monotonic", return_value=100) as clock,
        ):
            cleanup_expired_email_assets()
            cleanup_expired_email_assets()
            sweep.assert_called_once()
            clock.return_value = 161
            cleanup_expired_email_assets()
            self.assertEqual(sweep.call_count, 2)

    def test_throttled_sweeps_never_extend_cached_asset_expiry(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            self.settings(EMAIL_ASSET_CACHE_DIR=directory, EMAIL_ASSET_CACHE_TTL_SECONDS=60),
            patch.object(temp_cache, "_last_cleanup", None),
            patch.object(temp_cache.time, "time", return_value=1000) as clock,
            patch.object(temp_cache.time, "monotonic", return_value=100),
        ):
            cached = cache_image_bytes(image_bytes(), source_url="https://example.com/a.png")
            cleanup_expired_email_assets()
            clock.return_value = 1100
            cleanup_expired_email_assets()
            with self.assertRaisesMessage(EmailAssetCacheError, "expired"):
                read_cached_email_asset(cached.cache_key)
