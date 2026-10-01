from ..models import AssetRecord
from ..storage.keys import build_key
from ..storage.local import LocalStorageAdapter


def get_temp_storage_adapter():
    """
    The one place that decides which backend "temp" storage uses.
    Swap this (and get_persistent_storage_adapter) for an S3StorageAdapter
    later - nothing that calls these functions needs to change.
    """
    return LocalStorageAdapter(namespace="temp")


def get_persistent_storage_adapter():
    return LocalStorageAdapter(namespace="persistent")


def store_temp_asset(asset: AssetRecord, outcome) -> AssetRecord:
    """
    Writes a validated FetchOutcome's bytes to temp storage and updates
    the AssetRecord to match reality. Only called when `outcome.content`
    is present - i.e. fetch_and_validate succeeded AND no dedup match was
    found (a dedup hit already copied an existing stored_url and never
    needed new bytes written at all).
    """
    if outcome is None or outcome.content is None:
        raise ValueError("store_temp_asset requires a FetchOutcome with content")

    adapter = get_temp_storage_adapter()
    key = build_key(outcome.sha256, outcome.mime_type)
    stored_url = adapter.save(key, outcome.content, outcome.mime_type)

    asset.stored_url = stored_url
    asset.storage_provider = adapter.provider_name
    asset.status = AssetRecord.STATUS_TEMPORARY
    asset.save(
        update_fields=["stored_url", "storage_provider", "status", "updated_at"]
    )
    return asset