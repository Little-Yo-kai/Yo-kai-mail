from rest_framework import serializers


class BrandAnalysisRequestSerializer(serializers.Serializer):
    snapshot = serializers.DictField()

    def validate_snapshot(self, value):
        source = value.get("source")
        if not isinstance(source, dict):
            raise serializers.ValidationError(
                "WebsiteSnapshot must contain a source object."
            )

        if not source.get("requested_url") and not source.get("resolved_url"):
            raise serializers.ValidationError(
                "WebsiteSnapshot source must contain a URL."
            )

        return value
