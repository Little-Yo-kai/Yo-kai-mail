from rest_framework import serializers

from reference_design.serializers import (
    ALLOWED_IMAGE_TYPES,
    MAX_REFERENCE_IMAGE_BYTES,
)


class DemoGenerateSerializer(serializers.Serializer):
    url = serializers.URLField()
    reference_image = serializers.FileField(
        required=False,
        allow_null=True,
    )
    additional_instructions = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
    )

    def validate_reference_image(self, value):
        if value is None:
            return value

        content_type = getattr(value, "content_type", "")
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise serializers.ValidationError(
                "Reference image must be JPEG, PNG, or WebP."
            )

        if value.size > MAX_REFERENCE_IMAGE_BYTES:
            raise serializers.ValidationError(
                "Reference image must be 15 MB or smaller."
            )

        return value
