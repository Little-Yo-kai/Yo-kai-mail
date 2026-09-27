from django.conf import settings
from rest_framework import serializers


MAX_TEST_HTML_CHARS = 2_000_000


class CachedAssetRefSerializer(serializers.Serializer):
    cache_key = serializers.RegexField(
        regex=r"^[0-9a-f]{64}$",
        max_length=64,
    )
    source_url = serializers.URLField(max_length=4096)


class TestEmailSendSerializer(serializers.Serializer):
    to = serializers.EmailField()
    subject = serializers.CharField(max_length=998)
    html = serializers.CharField(
        trim_whitespace=False,
        max_length=MAX_TEST_HTML_CHARS,
    )
    cached_assets = CachedAssetRefSerializer(
        many=True,
        required=False,
        default=list,
    )
    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=256,
    )

    def validate_html(self, value):
        if not value.strip():
            raise serializers.ValidationError(
                "Rendered HTML cannot be empty."
            )
        return value

    def validate_cached_assets(self, value):
        if len(value) > settings.EMAIL_ASSET_MAX_INLINE_COUNT:
            raise serializers.ValidationError(
                "Too many cached assets for one test email."
            )

        seen_urls = set()
        for item in value:
            source_url = item["source_url"]
            if source_url in seen_urls:
                raise serializers.ValidationError(
                    "Duplicate cached asset source URL."
                )
            seen_urls.add(source_url)

        return value



class TestEmailStatusDataSerializer(serializers.Serializer):
    email_id = serializers.CharField()
    provider = serializers.CharField()
    last_event = serializers.CharField()
    created_at = serializers.CharField(
        required=False,
        allow_null=True,
    )
    to = serializers.ListField(
        child=serializers.EmailField(),
        required=False,
    )
    subject = serializers.CharField(
        required=False,
        allow_null=True,
    )


class TestEmailStatusResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = TestEmailStatusDataSerializer()
