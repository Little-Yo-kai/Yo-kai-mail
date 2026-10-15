"""
Phase 2 entry point: takes a pending AssetRecord and gets it as far as
possible without a storage adapter.

Three outcomes:
  - Deduplicated (by original_url or by content hash): another asset
    already has this exact content stored. We copy its stored_url and
    adopt its status (temporary/persistent) directly - no new storage
    write needed, so this IS a complete outcome, not a partial one.
  - Failed/unusable: saved directly onto the record as a terminal state.
  - Validated, no dedup match: mime_type/sha256/size_bytes are saved,
    but status is left at STATUS_FETCHING and stored_url stays empty -
    Phase 3's storage adapter still needs to write the bytes and then
    set status=temporary + stored_url. The FetchOutcome returned here
    carries those bytes so Phase 3 doesn't have to fetch again.
"""

from ..models import AssetRecord
from .fetch import fetch_and_validate, find_existing_by_hash, find_existing_by_url
from .storage_service import store_temp_asset


def _apply_dedup_match(asset: AssetRecord, match: AssetRecord, reason: str) -> None:
    asset.mime_type = match.mime_type
    asset.sha256 = match.sha256
    asset.size_bytes = match.size_bytes
    asset.stored_url = match.stored_url
    asset.storage_provider = match.storage_provider
    asset.status = match.status
    note = f"Deduplicated against {match.asset_id} ({reason})"
    asset.provenance_notes = "\n".join(filter(None, [asset.provenance_notes, note]))
    asset.save()


def validate_pending_asset(asset: AssetRecord):
    """
    Mutates and saves `asset` in place. Returns the FetchOutcome for
    Phase 3 to use (it holds the raw bytes on a successful, non-deduped
    fetch; on every other path there's nothing left for Phase 3 to do).
    """
    asset.status = AssetRecord.STATUS_FETCHING
    asset.save(update_fields=["status", "updated_at"])

    url_match = find_existing_by_url(asset.owner_reference, asset.original_url)
    if url_match:
        _apply_dedup_match(asset, url_match, reason="same URL")
        return None

    outcome = fetch_and_validate(asset.original_url)

    if outcome.status in (AssetRecord.STATUS_FAILED, AssetRecord.STATUS_UNUSABLE):
        asset.status = outcome.status
        asset.provenance_notes = "\n".join(
            filter(None, [asset.provenance_notes, outcome.note])
        )
        asset.save(update_fields=["status", "provenance_notes", "updated_at"])
        return outcome

    hash_match = find_existing_by_hash(outcome.sha256)
    if hash_match:
        _apply_dedup_match(asset, hash_match, reason="same content hash")
        return None

    asset.mime_type = outcome.mime_type
    asset.sha256 = outcome.sha256
    asset.size_bytes = outcome.size_bytes
    asset.save(update_fields=["mime_type", "sha256", "size_bytes", "updated_at"])
    return outcome


def process_asset(asset: AssetRecord) -> AssetRecord:
    """
    Full Phase 1-3 pipeline in one call: validate (with dedup), then
    actually store the bytes if nothing was deduplicated. This is what
    the future asset-creation endpoint (Phase 6) will call.
    """
    outcome = validate_pending_asset(asset)

    if outcome is not None and outcome.content is not None:
        store_temp_asset(asset, outcome)

    return asset