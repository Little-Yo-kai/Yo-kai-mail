import mimetypes


def build_key(sha256: str, mime_type: str) -> str:
    """
    Content-addressed key, sharded by the first two hex chars (the usual
    object-storage pattern, avoids one giant flat directory). Using the
    hash as the filename is what makes dedup's "reuse the existing
    stored_url" actually mean something on disk too - two AssetRecords
    with the same sha256 land at the exact same key.
    """
    ext = mimetypes.guess_extension(mime_type) or ""

    if ext == ".jpe":  # mimetypes' quirky default for image/jpeg on some platforms
        ext = ".jpg"

    return f"{sha256[:2]}/{sha256}{ext}"