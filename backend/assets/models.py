import uuid

from django.db import models


class AssetRecord(models.Model):
    STATUS_PENDING = "pending"
    STATUS_FETCHING = "fetching"
    STATUS_TEMPORARY = "temporary"
    STATUS_PERSISTENT = "persistent"
    STATUS_FAILED = "failed"
    STATUS_UNUSABLE = "unusable"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_FETCHING, "Fetching"),
        (STATUS_TEMPORARY, "Temporary"),
        (STATUS_PERSISTENT, "Persistent"),
        (STATUS_FAILED, "Failed"),
        (STATUS_UNUSABLE, "Unusable"),
    ]

    asset_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    owner_reference = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Campaign/brand owner this asset belongs to. Will become "
        "a Campaign FK once that model exists.",
    )

    original_url = models.URLField(max_length=2000)
    stored_url = models.URLField(max_length=2000, blank=True, null=True)

    mime_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveIntegerField(null=True, blank=True)

    # Indexed, not unique at the DB level: dedup scope (per-owner vs.
    # global) is a Phase 2 decision once the fetch pipeline exists, not a
    # constraint to bake into the contract now.
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)

    source = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. 'website_snapshot', 'reference_upload'.",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    storage_provider = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g. 'local', 's3'. Empty until stored somewhere.",
    )
    provenance_notes = models.TextField(
        blank=True,
        help_text="Free-text: which page/snapshot this came from, "
        "extraction confidence, why it failed, etc.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When set, a temporary asset eligible for cleanup after this time.",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"AssetRecord({self.asset_id}, {self.status})"