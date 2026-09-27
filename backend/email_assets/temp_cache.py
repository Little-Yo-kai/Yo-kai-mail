import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from django.conf import settings

from email_rendering.screenshot import _detect_image_mime, _host_is_public


MAX_REDIRECTS = 3
CACHE_KEY_PATTERN_LENGTH = 64

MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
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
    parsed = urlparse(value)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and _host_is_public(parsed.hostname)
    )


def _detect_asset_mime(
    body: bytes,
    content_type: str | None,
) -> str | None:
    detected = _detect_image_mime(body)
    if detected:
        return detected

    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    stripped = body.lstrip()

    if normalized == "image/svg+xml" and (
        stripped.startswith(b"<svg")
        or stripped.startswith(b"<?xml")
    ):
        return "image/svg+xml"

    return None


def _fetch_public_image(url: str) -> tuple[bytes, str, str]:
    current_url = url
    opener = urllib.request.build_opener(_NoRedirect())

    for _ in range(MAX_REDIRECTS + 1):
        if not _safe_public_http_url(current_url):
            raise EmailAssetCacheError(
                "Image URL is not a safe public HTTP(S) destination."
            )

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
            response = opener.open(request, timeout=8)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                if not location:
                    raise EmailAssetCacheError(
                        (
                            f"Image redirect returned HTTP {exc.code} "
                            "without Location."
                        )
                    ) from exc
                current_url = urljoin(current_url, location)
                continue

            raise EmailAssetCacheError(
                f"Image request returned HTTP {exc.code}."
            ) from exc
        except urllib.error.URLError as exc:
            raise EmailAssetCacheError(
                f"Image request failed: {exc.reason}"
            ) from exc

        content_type = response.headers.get("Content-Type")
        max_bytes = settings.EMAIL_ASSET_MAX_IMAGE_BYTES
        body = response.read(max_bytes + 1)

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
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(path)


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


def get_or_cache_remote_image(url: str) -> CachedEmailAsset:
    now = int(time.time())
    index_path = _url_index_path(url)
    index = _read_json(index_path)

    if index and int(index.get("expires_at") or 0) > now:
        cache_key = index.get("cache_key")
        if isinstance(cache_key, str):
            try:
                return read_cached_email_asset(
                    cache_key,
                    source_url=url,
                )
            except EmailAssetCacheError:
                pass

    body, mime_type, resolved_url = _fetch_public_image(url)
    cache_key = hashlib.sha256(body).hexdigest()
    extension = MIME_EXTENSIONS.get(mime_type, ".bin")
    filename = f"yokai-{cache_key[:16]}{extension}"

    created_at = now
    expires_at = now + settings.EMAIL_ASSET_CACHE_TTL_SECONDS

    body_path, metadata_path = _object_paths(cache_key)
    if not body_path.exists():
        temp_body_path = body_path.with_suffix(".bin.tmp")
        temp_body_path.write_bytes(body)
        temp_body_path.replace(body_path)

    metadata = {
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
