from rest_framework import serializers

from .models import AssetRecord


class AssetImportRequestSerializer(serializers.Serializer):

    owner_reference = serializers.CharField(max_length=255)
    original_url = serializers.URLField()
    source = serializers.CharField(max_length=100, required=False, allow_blank=True)


class AssetRecordSerializer(serializers.ModelSerializer):

    class Meta:
        model = AssetRecord
        fields = [
            "asset_id",
            "owner_reference",
            "original_url",
            "stored_url",
            "mime_type",
            "size_bytes",
            "sha256",
            "source",
            "status",
            "storage_provider",
            "provenance_notes",
            "created_at",
            "updated_at",
            "expires_at",
        ]
        read_only_fields = fields