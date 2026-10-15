from ..models import AssetRecord
from ..storage.keys import build_key
from .storage_service import get_persistent_storage_adapter, get_temp_storage_adapter


class InvalidPromotionError(Exception):
    """
    Raised when promotion is attempted on an asset that isn't eligible.
    Matches the plan doc's general principle that invalid state
    transitions must be rejected explicitly, not silently coerced.
    """


def promote_asset(asset: AssetRecord) -> AssetRecord:
    """
    Moves a temporary asset's bytes to persistent storage and updates the
    record to match. If another asset with identical content was already
    promoted, reuses that copy instead of writing (and paying for) a
    second one - the ticket's dedup guarantee applies to promotion too,
    not just the initial fetch.
    """
    if asset.status != AssetRecord.STATUS_TEMPORARY:
        raise InvalidPromotionError(
            f"Cannot promote asset in status={asset.status!r}; only "
            f"{AssetRecord.STATUS_TEMPORARY!r} assets can be promoted."
        )

    key = build_key(asset.sha256, asset.mime_type)
    temp_adapter = get_temp_storage_adapter()
    persistent_adapter = get_persistent_storage_adapter()

    if persistent_adapter.exists(key):
        stored_url = persistent_adapter.url_for(key)
    else:
        # Deliberately not wrapped in try/except: if the temp file is
        # missing despite status="temporary", that's an internal
        # inconsistency worth surfacing loudly, not masking as a normal
        # failed/unusable outcome.
        content = temp_adapter.read(key)
        stored_url = persistent_adapter.save(key, content, asset.mime_type)

    asset.stored_url = stored_url
    asset.storage_provider = persistent_adapter.provider_name
    asset.status = AssetRecord.STATUS_PERSISTENT
    asset.save(
        update_fields=["stored_url", "storage_provider", "status", "updated_at"]
    )

    # Best-effort cleanup, after the persistent copy is confirmed to
    # exist. A leftover temp file is wasted disk, not a correctness bug -
    # don't let a cleanup failure undo a successful promotion.
    try:
        temp_adapter.delete(key)
    except Exception:
        pass

    return asset