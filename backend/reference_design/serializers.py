from rest_framework import serializers


ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}
MAX_REFERENCE_IMAGE_BYTES = 15 * 1024 * 1024


class ReferenceDesignAnalyzeSerializer(serializers.Serializer):
    image = serializers.FileField()

    def validate_image(self, value):
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
