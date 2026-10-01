"""
Phase 2: turn an AssetRecord's original_url into validated bytes + a
content hash, or an explicit failed/unusable state. Does NOT write
anything to storage yet - that's Phase 3's job (the storage adapter).
This module only fetches, validates, hashes, and checks for existing
matches so Phase 3 knows whether it needs to store anything at all.
"""

import hashlib
import io

import requests
from PIL import Image, UnidentifiedImageError

from ..models import AssetRecord
from .ssrf import SSRFBlockedError, assert_safe_url

# Email clients and Yo-kai's own rendering pipeline only need these -
# deliberately excludes SVG (can carry scripts) and anything else that
# isn't a plain raster image.
ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}

MAX_ASSET_BYTES = 10 * 1024 * 1024  # 10 MB
FETCH_TIMEOUT_SECONDS = 10
MAX_REDIRECTS = 5

REQUEST_HEADERS = {
    "User-Agent": "YokaiMailAssetFetcher/1.0 (+https://example.com/bot)"
}


class FetchOutcome:
    """Plain result object - kept separate from the AssetRecord so this
    module has no side effects the caller doesn't explicitly apply."""

    def __init__(self, *, status, content=None, mime_type=None, sha256=None,
                 size_bytes=None, note=""):
        self.status = status
        self.content = content
        self.mime_type = mime_type
        self.sha256 = sha256
        self.size_bytes = size_bytes
        self.note = note


def _safe_get_following_redirects(url: str) -> requests.Response:
    """
    Fetches `url`, re-validating every redirect hop against SSRF rules
    before following it. requests' own allow_redirects=True would follow
    a redirect to an internal address without re-checking it, which
    defeats the point of validating the original URL.
    """
    current_url = url

    for _ in range(MAX_REDIRECTS + 1):
        assert_safe_url(current_url)

        response = requests.get(
            current_url,
            headers=REQUEST_HEADERS,
            timeout=FETCH_TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=False,
        )

        if response.is_redirect or response.is_permanent_redirect:
            next_url = response.headers.get("Location")
            response.close()
            if not next_url:
                raise SSRFBlockedError("Redirect with no Location header")
            current_url = requests.compat.urljoin(current_url, next_url)
            continue

        return response

    raise SSRFBlockedError("Too many redirects")


def _read_capped(response: requests.Response) -> bytes:
    """Reads the response body, aborting if it exceeds MAX_ASSET_BYTES -
    without this, a malicious or huge file could exhaust memory/disk
    before the size check ever runs."""
    chunks = []
    total = 0

    for chunk in response.iter_content(chunk_size=64 * 1024):
        total += len(chunk)
        if total > MAX_ASSET_BYTES:
            response.close()
            raise ValueError(f"Response exceeded {MAX_ASSET_BYTES} bytes")
        chunks.append(chunk)

    return b"".join(chunks)


def fetch_and_validate(url: str) -> FetchOutcome:
    """
    Fetches `url` and validates it's a real, supported, size-bounded
    image. Never raises for expected failure modes - always returns a
    FetchOutcome with an explicit status instead, per the ticket's
    "failed/unusable states, not silent broken images" requirement.
    """
    try:
        response = _safe_get_following_redirects(url)
    except SSRFBlockedError as exc:
        return FetchOutcome(status=AssetRecord.STATUS_FAILED, note=str(exc))
    except requests.RequestException as exc:
        return FetchOutcome(status=AssetRecord.STATUS_FAILED, note=f"Network error: {exc}")

    try:
        if response.status_code != 200:
            return FetchOutcome(
                status=AssetRecord.STATUS_FAILED,
                note=f"HTTP {response.status_code}",
            )

        try:
            content = _read_capped(response)
        except ValueError as exc:
            return FetchOutcome(status=AssetRecord.STATUS_UNUSABLE, note=str(exc))

    finally:
        response.close()

    if not content:
        return FetchOutcome(status=AssetRecord.STATUS_UNUSABLE, note="Empty response body")

    # Validate actual image bytes - never trust the URL extension or the
    # server's Content-Type header alone; both can lie or be missing.
    try:
        image = Image.open(io.BytesIO(content))
        image.verify()
        detected_format = image.format  # e.g. "PNG", "JPEG"
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return FetchOutcome(
            status=AssetRecord.STATUS_UNUSABLE,
            note=f"Not a valid image: {exc}",
        )

    mime_type = Image.MIME.get(detected_format, "")
    if mime_type not in ALLOWED_MIME_TYPES:
        return FetchOutcome(
            status=AssetRecord.STATUS_UNUSABLE,
            note=f"Unsupported image type: {mime_type or detected_format}",
        )

    sha256 = hashlib.sha256(content).hexdigest()

    return FetchOutcome(
        status=AssetRecord.STATUS_TEMPORARY,
        content=content,
        mime_type=mime_type,
        sha256=sha256,
        size_bytes=len(content),
    )


def find_existing_by_hash(sha256: str):
    """
    Dedup check: an already-stored asset (temporary or persistent) with
    identical content. Scoped globally, not per-owner - two campaigns
    referencing the exact same image byte-for-byte share one stored copy.
    Flagging this as a deliberate scope choice: switch to
    `.filter(owner_reference=..., sha256=sha256)` if per-owner isolation
    turns out to matter more than storage savings.
    """
    return (
        AssetRecord.objects.filter(
            sha256=sha256,
            status__in=[AssetRecord.STATUS_TEMPORARY, AssetRecord.STATUS_PERSISTENT],
        )
        .exclude(stored_url__isnull=True)
        .exclude(stored_url="")
        .first()
    )


def find_existing_by_url(owner_reference: str, original_url: str):
    """
    Cheap pre-check to skip re-downloading the exact same URL for the
    same owner before we even know its content hash. This does not catch
    the same image served from two different URLs - find_existing_by_hash
    (after downloading) is what the ticket's dedup guarantee relies on.
    """
    return AssetRecord.objects.filter(
        owner_reference=owner_reference,
        original_url=original_url,
        status__in=[AssetRecord.STATUS_TEMPORARY, AssetRecord.STATUS_PERSISTENT],
    ).first()