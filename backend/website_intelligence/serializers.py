from rest_framework import serializers


class WebsiteImportRequestSerializer(serializers.Serializer):
    url = serializers.URLField()
