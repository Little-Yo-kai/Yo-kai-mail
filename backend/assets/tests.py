import io
import shutil
import tempfile
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from .models import AssetRecord
from .services.fetch import fetch_and_validate, find_existing_by_hash
from .services.pipeline import process_asset, validate_pending_asset
from .services.promotion import InvalidPromotionError, promote_asset
from .services.ssrf import SSRFBlockedError, assert_safe_url
from .storage.keys import build_key
from .storage.local import LocalStorageAdapter


def _make_png_bytes(color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


class SSRFTests(TestCase):
    def test_blocks_private_ip(self):
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("10.0.0.5", 0))]):
            with self.assertRaises(SSRFBlockedError):
                assert_safe_url("http://internal.example.com/logo.png")

    def test_blocks_loopback(self):
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]):
            with self.assertRaises(SSRFBlockedError):
                assert_safe_url("http://sneaky.example.com/logo.png")

    def test_blocks_link_local_metadata(self):
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("169.254.169.254", 0))]):
            with self.assertRaises(SSRFBlockedError):
                assert_safe_url("http://metadata.example.com/logo.png")

    def test_blocks_bad_scheme(self):
        with self.assertRaises(SSRFBlockedError):
            assert_safe_url("ftp://example.com/logo.png")

    def test_blocks_localhost_hostname(self):
        with self.assertRaises(SSRFBlockedError):
            assert_safe_url("http://localhost/logo.png")

    def test_allows_public_ip(self):
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
            assert_safe_url("https://example.com/logo.png")  # should not raise


class FetchAndValidateTests(TestCase):
    def _mock_response(self, content, status_code=200):
        response = Mock()
        response.status_code = status_code
        response.is_redirect = False
        response.is_permanent_redirect = False
        response.iter_content = lambda chunk_size: [content]
        response.close = lambda: None
        return response

    @patch("assets.services.fetch.assert_safe_url")
    @patch("assets.services.fetch.requests.get")
    def test_accepts_valid_png(self, mock_get, mock_ssrf):
        mock_get.return_value = self._mock_response(_make_png_bytes())

        outcome = fetch_and_validate("https://example.com/logo.png")

        self.assertEqual(outcome.status, AssetRecord.STATUS_TEMPORARY)
        self.assertEqual(outcome.mime_type, "image/png")
        self.assertIsNotNone(outcome.sha256)
        self.assertEqual(len(outcome.sha256), 64)

    @patch("assets.services.fetch.assert_safe_url")
    @patch("assets.services.fetch.requests.get")
    def test_rejects_non_image_bytes(self, mock_get, mock_ssrf):
        mock_get.return_value = self._mock_response(b"not an image, just text")

        outcome = fetch_and_validate("https://example.com/fake.png")

        self.assertEqual(outcome.status, AssetRecord.STATUS_UNUSABLE)

    @patch("assets.services.fetch.assert_safe_url")
    @patch("assets.services.fetch.requests.get")
    def test_rejects_oversized_response(self, mock_get, mock_ssrf):
        big_chunk = b"0" * (1024 * 1024)
        response = Mock()
        response.status_code = 200
        response.is_redirect = False
        response.is_permanent_redirect = False
        # 11 chunks of 1MB > the 10MB cap
        response.iter_content = lambda chunk_size: [big_chunk] * 11
        response.close = lambda: None
        mock_get.return_value = response

        outcome = fetch_and_validate("https://example.com/huge.png")

        self.assertEqual(outcome.status, AssetRecord.STATUS_UNUSABLE)

    @patch("assets.services.fetch.assert_safe_url", side_effect=SSRFBlockedError("blocked"))
    def test_ssrf_block_surfaces_as_failed(self, mock_ssrf):
        outcome = fetch_and_validate("http://169.254.169.254/secret")
        self.assertEqual(outcome.status, AssetRecord.STATUS_FAILED)


class DedupTests(TestCase):
    def test_find_existing_by_hash_matches_temporary_asset(self):
        existing = AssetRecord.objects.create(
            owner_reference="campaign-1",
            original_url="https://a.example.com/logo.png",
            stored_url="https://cdn.yokai.example/assets/abc.png",
            sha256="a" * 64,
            status=AssetRecord.STATUS_TEMPORARY,
        )

        match = find_existing_by_hash("a" * 64)
        self.assertEqual(match.asset_id, existing.asset_id)

    def test_find_existing_by_hash_ignores_failed_asset(self):
        AssetRecord.objects.create(
            owner_reference="campaign-1",
            original_url="https://a.example.com/logo.png",
            sha256="b" * 64,
            status=AssetRecord.STATUS_FAILED,
        )

        self.assertIsNone(find_existing_by_hash("b" * 64))


class PipelineTests(TestCase):
    @patch("assets.services.pipeline.fetch_and_validate")
    def test_dedup_by_url_skips_fetch_entirely(self, mock_fetch):
        AssetRecord.objects.create(
            owner_reference="campaign-1",
            original_url="https://a.example.com/logo.png",
            stored_url="https://cdn.yokai.example/assets/abc.png",
            sha256="c" * 64,
            status=AssetRecord.STATUS_PERSISTENT,
        )

        new_asset = AssetRecord.objects.create(
            owner_reference="campaign-1",
            original_url="https://a.example.com/logo.png",
        )

        validate_pending_asset(new_asset)

        new_asset.refresh_from_db()
        self.assertEqual(new_asset.status, AssetRecord.STATUS_PERSISTENT)
        self.assertEqual(new_asset.stored_url, "https://cdn.yokai.example/assets/abc.png")
        mock_fetch.assert_not_called()


class BuildKeyTests(TestCase):
    def test_png_gets_png_extension(self):
        key = build_key("a" * 64, "image/png")
        self.assertEqual(key, f"aa/{'a' * 64}.png")

    def test_jpeg_normalizes_to_dot_jpg(self):
        key = build_key("b" * 64, "image/jpeg")
        self.assertTrue(key.endswith(".jpg"))

    def test_shards_by_first_two_hex_chars(self):
        key = build_key("deadbeef" + "0" * 56, "image/png")
        self.assertTrue(key.startswith("de/"))


class LocalStorageAdapterTests(TestCase):
    def setUp(self):
        self.tmp_media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_media_root, ignore_errors=True)
        self.override = override_settings(
            MEDIA_ROOT=self.tmp_media_root,
            ASSET_PUBLIC_BASE_URL="http://testserver",
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

        self.adapter = LocalStorageAdapter(namespace="temp")

    def test_save_then_read_round_trips(self):
        url = self.adapter.save("ab/abcdef.png", b"hello bytes", "image/png")

        self.assertTrue(self.adapter.exists("ab/abcdef.png"))
        self.assertEqual(self.adapter.read("ab/abcdef.png"), b"hello bytes")
        self.assertEqual(
            url, "http://testserver/media/assets/temp/ab/abcdef.png"
        )

    def test_delete_is_idempotent(self):
        self.adapter.save("cd/x.png", b"data", "image/png")
        self.adapter.delete("cd/x.png")
        self.assertFalse(self.adapter.exists("cd/x.png"))
        self.adapter.delete("cd/x.png")  # should not raise

    def test_path_traversal_key_is_rejected(self):
        with self.assertRaises(ValueError):
            self.adapter.save("../../etc/passwd", b"data", "image/png")

    def test_temp_and_persistent_namespaces_are_isolated(self):
        temp_adapter = LocalStorageAdapter(namespace="temp")
        persistent_adapter = LocalStorageAdapter(namespace="persistent")

        temp_adapter.save("ab/shared.png", b"temp bytes", "image/png")

        self.assertTrue(temp_adapter.exists("ab/shared.png"))
        self.assertFalse(persistent_adapter.exists("ab/shared.png"))


class ProcessAssetEndToEndTests(TestCase):
    def setUp(self):
        self.tmp_media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_media_root, ignore_errors=True)
        self.override = override_settings(
            MEDIA_ROOT=self.tmp_media_root,
            ASSET_PUBLIC_BASE_URL="http://testserver",
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

    def _mock_png_response(self):
        response = Mock()
        response.status_code = 200
        response.is_redirect = False
        response.is_permanent_redirect = False
        response.iter_content = lambda chunk_size: [_make_png_bytes()]
        response.close = lambda: None
        return response

    @patch("assets.services.fetch.assert_safe_url")
    @patch("assets.services.fetch.requests.get")
    def test_new_asset_reaches_temporary_with_real_stored_url(self, mock_get, mock_ssrf):
        mock_get.return_value = self._mock_png_response()

        asset = AssetRecord.objects.create(
            owner_reference="campaign-1",
            original_url="https://example.com/logo.png",
        )

        process_asset(asset)
        asset.refresh_from_db()

        self.assertEqual(asset.status, AssetRecord.STATUS_TEMPORARY)
        self.assertEqual(asset.storage_provider, "local")
        self.assertTrue(asset.stored_url.startswith("http://testserver/media/assets/temp/"))

        # Actually stored, not just claimed
        adapter = LocalStorageAdapter(namespace="temp")
        key = build_key(asset.sha256, asset.mime_type)
        self.assertTrue(adapter.exists(key))

    @patch("assets.services.fetch.assert_safe_url")
    @patch("assets.services.fetch.requests.get")
    def test_second_identical_image_dedups_and_does_not_write_again(self, mock_get, mock_ssrf):
        mock_get.return_value = self._mock_png_response()

        first = AssetRecord.objects.create(
            owner_reference="campaign-1", original_url="https://a.example.com/logo.png"
        )
        process_asset(first)
        first.refresh_from_db()

        second = AssetRecord.objects.create(
            owner_reference="campaign-2", original_url="https://b.example.com/logo-mirror.png"
        )

        with patch("assets.services.pipeline.store_temp_asset") as mock_store:
            process_asset(second)
            mock_store.assert_not_called()

        second.refresh_from_db()
        self.assertEqual(second.stored_url, first.stored_url)
        self.assertEqual(second.status, first.status)

    @patch("assets.services.fetch.assert_safe_url", side_effect=SSRFBlockedError("blocked"))
    def test_blocked_asset_never_touches_storage(self, mock_ssrf):
        asset = AssetRecord.objects.create(
            owner_reference="campaign-1", original_url="http://169.254.169.254/secret"
        )

        process_asset(asset)
        asset.refresh_from_db()

        self.assertEqual(asset.status, AssetRecord.STATUS_FAILED)
        self.assertEqual(asset.stored_url, None)
        self.assertEqual(asset.storage_provider, "")


class PromoteAssetTests(TestCase):
    def setUp(self):
        self.tmp_media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_media_root, ignore_errors=True)
        self.override = override_settings(
            MEDIA_ROOT=self.tmp_media_root,
            ASSET_PUBLIC_BASE_URL="http://testserver",
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

    def _mock_png_response(self):
        response = Mock()
        response.status_code = 200
        response.is_redirect = False
        response.is_permanent_redirect = False
        response.iter_content = lambda chunk_size: [_make_png_bytes()]
        response.close = lambda: None
        return response

    def test_promote_rejects_non_temporary_status(self):
        asset = AssetRecord.objects.create(
            owner_reference="campaign-1",
            original_url="https://example.com/logo.png",
            status=AssetRecord.STATUS_PENDING,
        )
        with self.assertRaises(InvalidPromotionError):
            promote_asset(asset)

    @patch("assets.services.fetch.assert_safe_url")
    @patch("assets.services.fetch.requests.get")
    def test_promote_moves_bytes_from_temp_to_persistent(self, mock_get, mock_ssrf):
        mock_get.return_value = self._mock_png_response()

        asset = AssetRecord.objects.create(
            owner_reference="campaign-1", original_url="https://example.com/logo.png"
        )
        process_asset(asset)
        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetRecord.STATUS_TEMPORARY)

        temp_adapter = LocalStorageAdapter(namespace="temp")
        persistent_adapter = LocalStorageAdapter(namespace="persistent")
        key = build_key(asset.sha256, asset.mime_type)
        self.assertTrue(temp_adapter.exists(key))
        self.assertFalse(persistent_adapter.exists(key))

        promote_asset(asset)
        asset.refresh_from_db()

        self.assertEqual(asset.status, AssetRecord.STATUS_PERSISTENT)
        self.assertTrue(asset.stored_url.startswith("http://testserver/media/assets/persistent/"))
        self.assertTrue(persistent_adapter.exists(key))
        self.assertFalse(temp_adapter.exists(key))  # temp copy cleaned up

    @patch("assets.services.fetch.assert_safe_url")
    @patch("assets.services.fetch.requests.get")
    def test_promoting_second_identical_asset_reuses_persistent_copy(self, mock_get, mock_ssrf):
        mock_get.return_value = self._mock_png_response()

        first = AssetRecord.objects.create(
            owner_reference="campaign-1", original_url="https://a.example.com/logo.png"
        )
        process_asset(first)
        first.refresh_from_db()
        promote_asset(first)
        first.refresh_from_db()

        second = AssetRecord.objects.create(
            owner_reference="campaign-2", original_url="https://b.example.com/logo-mirror.png"
        )
        process_asset(second)  # dedups against `first` at the temp stage already
        second.refresh_from_db()
        self.assertEqual(second.status, AssetRecord.STATUS_PERSISTENT)  # inherited from first via dedup

        # Force it back to temporary to exercise promote_asset's own
        # dedup path independently of the fetch-stage dedup above.
        second.status = AssetRecord.STATUS_TEMPORARY
        second.save(update_fields=["status"])

        persistent_adapter = LocalStorageAdapter(namespace="persistent")
        with patch.object(persistent_adapter.__class__, "save") as mock_save:
            promote_asset(second)
            mock_save.assert_not_called()  # already existed, reused instead

        second.refresh_from_db()
        self.assertEqual(second.status, AssetRecord.STATUS_PERSISTENT)
        self.assertEqual(second.stored_url, first.stored_url)


class AssetApiTests(TestCase):
    """
    Hits real URLs through Django's URL routing, not the service functions
    directly - proves urls.py/views.py actually wire together, not just
    that the underlying pipeline works.
    """

    def setUp(self):
        self.client = APIClient()
        self.tmp_media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_media_root, ignore_errors=True)
        self.override = override_settings(
            MEDIA_ROOT=self.tmp_media_root,
            ASSET_PUBLIC_BASE_URL="http://testserver",
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

    def _mock_png_response(self):
        response = Mock()
        response.status_code = 200
        response.is_redirect = False
        response.is_permanent_redirect = False
        response.iter_content = lambda chunk_size: [_make_png_bytes()]
        response.close = lambda: None
        return response

    @patch("assets.services.fetch.assert_safe_url")
    @patch("assets.services.fetch.requests.get")
    def test_import_promote_detail_full_http_flow(self, mock_get, mock_ssrf):
        mock_get.return_value = self._mock_png_response()

        # 1. Import via real POST
        response = self.client.post(
            "/api/assets/import/",
            {"owner_reference": "campaign-1", "original_url": "https://example.com/logo.png"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["status"], AssetRecord.STATUS_TEMPORARY)
        asset_id = body["data"]["asset_id"]
        self.assertTrue(body["data"]["stored_url"].startswith("http://testserver/media/assets/temp/"))

        # 2. Detail via real GET
        response = self.client.get(f"/api/assets/{asset_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["asset_id"], asset_id)

        # 3. List, filtered by owner, via real GET
        response = self.client.get("/api/assets/", {"owner_reference": "campaign-1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)

        # 4. Promote via real POST
        response = self.client.post(f"/api/assets/{asset_id}/promote/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["status"], AssetRecord.STATUS_PERSISTENT)
        self.assertTrue(body["data"]["stored_url"].startswith("http://testserver/media/assets/persistent/"))

        # 5. Promoting again should now fail explicitly (already promoted)
        response = self.client.post(f"/api/assets/{asset_id}/promote/")
        self.assertEqual(response.status_code, 409)

    def test_promote_unknown_asset_returns_404(self):
        response = self.client.post(
            "/api/assets/00000000-0000-0000-0000-000000000000/promote/"
        )
        self.assertEqual(response.status_code, 404)

    def test_import_missing_fields_returns_400(self):
        response = self.client.post("/api/assets/import/", {}, format="json")
        self.assertEqual(response.status_code, 400)

    @patch("assets.services.fetch.assert_safe_url", side_effect=SSRFBlockedError("blocked"))
    def test_import_blocked_url_still_creates_record_with_failed_status(self, mock_ssrf):
        response = self.client.post(
            "/api/assets/import/",
            {"owner_reference": "campaign-1", "original_url": "http://169.254.169.254/x"},
            format="json",
        )
        # Not an HTTP error - the record exists, just marked failed. The
        # caller (Friend 4/5) checks `status`, not the HTTP status code,
        # to know if an asset is usable.
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["status"], AssetRecord.STATUS_FAILED)