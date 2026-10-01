"""
Storage adapter interface. Every backend (local filesystem, S3/R2, ...)
implements this and nothing else. EmailDesign, the renderer, and delivery
only ever see the URL save() returns - never which class produced it.
That's the ticket's swappability requirement: change which adapter gets
constructed, and no caller-side code changes.
"""

from abc import ABC, abstractmethod


class StorageAdapter(ABC):

    #: Short identifier stored on AssetRecord.storage_provider, e.g.
    #: "local", "s3". Set by each concrete subclass.
    provider_name: str

    @abstractmethod
    def save(self, key: str, content: bytes, content_type: str) -> str:
        """
        Writes `content` under `key` and returns a stable, absolute,
        email-safe URL - one a recipient's mail client can fetch directly,
        with no auth, no signed-URL expiry assumptions baked into callers.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Whether `key` is already stored - used by dedup/promotion to
        avoid redundant writes."""

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Raises FileNotFoundError (or equivalent) if `key` doesn't exist."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """No-op if `key` doesn't exist - callers shouldn't have to check
        existence first just to clean up."""

    @abstractmethod
    def url_for(self, key: str) -> str:
        """
        Returns the stable URL for `key` without writing anything - used
        when promotion finds the content already stored (e.g. another
        asset with identical content was promoted first) and only needs
        the URL, not a redundant write.
        """