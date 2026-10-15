"""
Local filesystem storage - the "local/dev storage first" half of the
ticket's storage adapter requirement. Fine for local dev and small-team
testing; not meant for production-scale serving (that's the S3/R2
adapter's job later), but structurally identical from any caller's POV.
"""

from pathlib import Path

from django.conf import settings

from .base import StorageAdapter


class LocalStorageAdapter(StorageAdapter):

    provider_name = "local"

    def __init__(self, namespace: str):
        """
        `namespace` is "temp" or "persistent" - keeping the two stages in
        physically separate directories is what makes promotion a real
        file move, not just a status flag that could drift from reality.
        """
        self.namespace = namespace
        self.base_dir = (Path(settings.MEDIA_ROOT) / "assets" / namespace).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        path = (self.base_dir / key).resolve()

        # Defensive: a malformed or malicious key (e.g. containing ../)
        # must never resolve outside this adapter's own directory.
        if path != self.base_dir and self.base_dir not in path.parents:
            raise ValueError(f"Invalid key escapes storage directory: {key!r}")

        return path

    def save(self, key: str, content: bytes, content_type: str) -> str:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return self.url_for(key)

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()

    def read(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path_for(key)
        if path.exists():
            path.unlink()

    def url_for(self, key: str) -> str:
        base = settings.ASSET_PUBLIC_BASE_URL.rstrip("/")
        media_url = settings.MEDIA_URL.strip("/")
        return f"{base}/{media_url}/assets/{self.namespace}/{key}"