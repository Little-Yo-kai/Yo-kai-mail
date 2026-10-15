from rest_framework import serializers


class WebsiteImportRequestSerializer(serializers.Serializer):
    url = serializers.URLField()
    limit = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=100,
    )