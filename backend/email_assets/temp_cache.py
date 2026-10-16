import hashlib
import io
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from urllib.parse import urljoin

from django.conf import settings
from PIL import Image, UnidentifiedImageError

from assets.services.ssrf import (
    SSRFBlockedError,
    assert_safe_url,
    normalize_public_asset_url,
)

MAX_REDIRECTS = 3
CACHE_KEY_PATTERN_LENGTH = 64
CLEANUP_INTERVAL_SECONDS = 60
_cleanup_lock = Lock()
_last_cleanup = None
# Fixed stripes bound lock memory even when callers supply many unique URLs.
_url_fetch_locks = tuple(Lock() for _ in range(64))

MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class CachedEmailAsset:
    cache_key: str
    source_url: str
    resolved_url: str
    mime_type: str
    filename: str
    body: bytes
    created_at: int
    expires_at: int
    cache_hit: bool = False

    def public_manifest(self) -> dict:
        return {
            "cache_key": self.cache_key,
            "source_url": self.source_url,
            "resolved_url": self.resolved_url,
            "mime_type": self.mime_type,
            "filename": self.filename,
            "bytes": len(self.body),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "cache_hit": self.cache_hit,
        }


class EmailAssetCacheError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _cache_root() -> Path:
    root = Path(settings.EMAIL_ASSET_CACHE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _objects_dir() -> Path:
    path = _cache_root() / "objects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _urls_dir() -> Path:
    path = _cache_root() / "urls"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_public_http_url(value: str) -> bool:
    try:
        assert_safe_url(value)
    except SSRFBlockedError:
        return False
    return True


def _detect_asset_mime(
    body: bytes,
    content_type: str | None,
) -> str | None:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized and normalized not in {
        *MIME_EXTENSIONS, "application/octet-stream", "image/svg+xml",
    }:
        return None

    if normalized == "image/svg+xml":
        # An XML declaration alone does not establish that this is an image.
        if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
            return None
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return None
        if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
            return None
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1].lower()
            if tag in {"script", "foreignobject"}:
                return None
            css_values = [element.text or ""] if tag == "style" else []
            for key, value in element.attrib.items():
                attribute = key.rsplit("}", 1)[-1].lower()
                if attribute.startswith("on"):
                    return None
                if attribute == "href" and not value.strip().startswith("#"):
                    return None
                css_values.append(value)
            for css in css_values:
                if "@import" in css.lower() or any(
                    not target.strip().strip("\"'").startswith("#")
                    for target in re.findall(r"url\s*\(([^)]*)\)", css, re.IGNORECASE)
                ):
                    return None
        return normalized

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as image:
                mime_type = Image.MIME.get(image.format)
                image.verify()
    except (
        UnidentifiedImageError, OSError, ValueError,
        Image.DecompressionBombError, Image.DecompressionBombWarning,
    ):
        return None

    if mime_type in MIME_EXTENSIONS and mime_type != "image/svg+xml":
        return mime_type

    return None


def _fetch_public_image(url: str, *, timeout: float = 8) -> tuple[bytes, str, str]:
    current_url = url
    opener = urllib.request.build_opener(_NoRedirect())
    deadline = time.monotonic() + timeout

    for _ in range(MAX_REDIRECTS + 1):
        normalized_url = normalize_public_asset_url(current_url)
        if not normalized_url or not _safe_public_http_url(normalized_url):
            raise EmailAssetCacheError(
                "Image URL is not a safe public HTTP(S) destination."
            )
        current_url = normalized_url

        request = urllib.request.Request(
            current_url,
            headers={
                "User-Agent": "Yo-kai-Mail-Demo/1.0",
                "Accept": (
                    "image/avif,image/webp,image/apng,image/svg+xml,"
                    "image/*,*/*;q=0.8"
                ),
            },
            method="GET",
        )

        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EmailAssetCacheError("Preview image download timed out.")
            response = opener.open(request, timeout=remaining)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                exc.close()
                if not location:
                    raise EmailAssetCacheError(
                        f"Image redirect returned HTTP {exc.code} "
                        "without Location."
                    ) from exc
                current_url = urljoin(current_url, location)
                continue

            exc.close()
            raise EmailAssetCacheError(
                f"Image request returned HTTP {exc.code}."
            ) from exc
        except urllib.error.URLError as exc:
            raise EmailAssetCacheError(
                f"Image request failed: {exc.reason}"
            ) from exc

        try:
            content_type = response.headers.get("Content-Type")
            max_bytes = settings.EMAIL_ASSET_MAX_IMAGE_BYTES
            chunks = []
            size = 0
            while size <= max_bytes:
                if time.monotonic() >= deadline:
                    raise EmailAssetCacheError("Preview image download timed out.")
                chunk = response.read1(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            body = b"".join(chunks)
        finally:
            response.close()

        if len(body) > max_bytes:
            raise EmailAssetCacheError(
                "Image exceeds the temporary asset size limit."
            )

        mime_type = _detect_asset_mime(body, content_type)
        if not mime_type:
            raise EmailAssetCacheError(
                "Remote response was not a supported image."
            )

        return body, mime_type, current_url

    raise EmailAssetCacheError(
        "Image exceeded the maximum redirect count."
    )


def _url_index_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return _urls_dir() / f"{digest}.json"


def _object_paths(cache_key: str) -> tuple[Path, Path]:
    if (
        len(cache_key) != CACHE_KEY_PATTERN_LENGTH
        or any(char not in "0123456789abcdef" for char in cache_key)
    ):
        raise EmailAssetCacheError("Invalid temporary asset cache key.")

    base = _objects_dir() / cache_key
    return base.with_suffix(".bin"), base.with_suffix(".json")


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _write_json(path: Path, payload: dict) -> None:
    _atomic_write(path, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _atomic_write(path: Path, body: bytes) -> None:
    # Concurrent generations can normalize the same photo. Give each writer
    # its own temporary file so one rename cannot remove another writer's file.
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # Windows can briefly deny replacement while another writer
                # replaces the same content-addressed cache object/index.
                if attempt == 4:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_cached_email_asset(
    cache_key: str,
    *,
    source_url: str | None = None,
) -> CachedEmailAsset:
    body_path, metadata_path = _object_paths(cache_key)
    metadata = _read_json(metadata_path)

    if not metadata or not body_path.exists():
        raise EmailAssetCacheError(
            "Temporary email asset is not available."
        )

    now = int(time.time())
    expires_at = int(metadata.get("expires_at") or 0)
    if expires_at <= now:
        body_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        raise EmailAssetCacheError(
            "Temporary email asset has expired. Regenerate the email."
        )

    try:
        body = body_path.read_bytes()
    except OSError as exc:
        raise EmailAssetCacheError(
            "Temporary email asset could not be read."
        ) from exc

    if metadata.get("encoding_version") != 1:
        return cache_image_bytes(
            body,
            source_url=source_url or metadata.get("source_url") or "",
            resolved_url=metadata.get("resolved_url"),
        )

    return CachedEmailAsset(
        cache_key=cache_key,
        source_url=source_url or metadata.get("source_url") or "",
        resolved_url=metadata.get("resolved_url") or "",
        mime_type=metadata.get("mime_type") or "application/octet-stream",
        filename=metadata.get("filename") or f"{cache_key}.bin",
        body=body,
        created_at=int(metadata.get("created_at") or 0),
        expires_at=expires_at,
        cache_hit=True,
    )


def _read_url_cached_asset(url: str, index_path: Path) -> CachedEmailAsset | None:
    index = _read_json(index_path)

    if index and int(index.get("expires_at") or 0) > int(time.time()):
        cache_key = index.get("cache_key")
        if isinstance(cache_key, str):
            try:
                return read_cached_email_asset(
                    cache_key,
                    source_url=url,
                )
            except EmailAssetCacheError:
                pass
    return None


def get_or_cache_remote_image(url: str, *, timeout: float = 8) -> CachedEmailAsset:
    deadline = time.monotonic() + timeout
    index_path = _url_index_path(url)
    cached = _read_url_cached_asset(url, index_path)
    if cached is not None:
        return cached

    lock = _url_fetch_locks[int(index_path.stem[:2], 16) % len(_url_fetch_locks)]
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not lock.acquire(timeout=remaining):
        raise EmailAssetCacheError("Preview image download timed out.")
    try:
        # A concurrent preview/send may have populated the cache while we waited.
        cached = _read_url_cached_asset(url, index_path)
        if cached is not None:
            return cached
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EmailAssetCacheError("Preview image download timed out.")
        body, _mime_type, resolved_url = _fetch_public_image(url, timeout=remaining)
        return cache_image_bytes(body, source_url=url, resolved_url=resolved_url)
    finally:
        lock.release()


def cache_image_bytes(
    body: bytes,
    *,
    source_url: str,
    resolved_url: str | None = None,
) -> CachedEmailAsset:
    """Store validated raster bytes shared by preview, edits and CID delivery."""
    if not body or len(body) > settings.EMAIL_ASSET_MAX_IMAGE_BYTES:
        raise EmailAssetCacheError("Image is empty or exceeds the image size limit.")
    try:
        with Image.open(io.BytesIO(body)) as image:
            image.verify()
        with Image.open(io.BytesIO(body)) as image:
            if image.width < 8 or image.height < 8:
                raise EmailAssetCacheError("Tracking pixels and empty placeholders cannot be used as email images.")
            if image.width * image.height > 30_000_000:
                raise EmailAssetCacheError("Image dimensions are too large.")
            image.load()
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                image.convert("RGBA").save(output, format="PNG", optimize=True)
                mime_type = "image/png"
            else:
                image.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
                mime_type = "image/jpeg"
            body = output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise EmailAssetCacheError("File is not a supported, valid raster image.") from exc
    if len(body) > settings.EMAIL_ASSET_MAX_IMAGE_BYTES:
        raise EmailAssetCacheError("Converted image exceeds the image size limit.")

    now = int(time.time())
    cache_key = hashlib.sha256(body).hexdigest()
    url = source_url.replace("{cache_key}", cache_key)
    resolved_url = resolved_url or url
    index_path = _url_index_path(url)
    extension = MIME_EXTENSIONS.get(mime_type, ".bin")
    filename = f"yokai-{cache_key[:16]}{extension}"

    created_at = now
    expires_at = now + settings.EMAIL_ASSET_CACHE_TTL_SECONDS

    body_path, metadata_path = _object_paths(cache_key)
    if not body_path.exists():
        _atomic_write(body_path, body)

    metadata = {
        "encoding_version": 1,
        "cache_key": cache_key,
        "source_url": url,
        "resolved_url": resolved_url,
        "mime_type": mime_type,
        "filename": filename,
        "created_at": created_at,
        "expires_at": expires_at,
    }
    _write_json(metadata_path, metadata)
    _write_json(
        index_path,
        {
            "cache_key": cache_key,
            "source_url": url,
            "expires_at": expires_at,
        },
    )

    return CachedEmailAsset(
        cache_key=cache_key,
        source_url=url,
        resolved_url=resolved_url,
        mime_type=mime_type,
        filename=filename,
        body=body,
        created_at=created_at,
        expires_at=expires_at,
        cache_hit=False,
    )


def cleanup_expired_email_assets() -> None:
    global _last_cleanup
    if not _cleanup_lock.acquire(blocking=False):
        return
    try:
        root = os.path.abspath(settings.EMAIL_ASSET_CACHE_DIR)
        monotonic = time.monotonic()
        if (
            _last_cleanup is not None
            and _last_cleanup[0] == root
            and monotonic - _last_cleanup[1] < CLEANUP_INTERVAL_SECONDS
        ):
            return
        _remove_expired_email_assets()
        _last_cleanup = (root, time.monotonic())
    finally:
        _cleanup_lock.release()


def _remove_expired_email_assets() -> None:
    now = int(time.time())

    for metadata_path in _objects_dir().glob("*.json"):
        metadata = _read_json(metadata_path)
        if metadata and int(metadata.get("expires_at") or 0) > now:
            continue

        cache_key = metadata_path.stem
        body_path, _ = _object_paths(cache_key)
        body_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)

    for index_path in _urls_dir().glob("*.json"):
        index = _read_json(index_path)
        if not index or int(index.get("expires_at") or 0) <= now:
            index_path.unlink(missing_ok=True)
