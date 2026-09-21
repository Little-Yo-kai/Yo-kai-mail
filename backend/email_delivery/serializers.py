from rest_framework import serializers


MAX_TEST_HTML_CHARS = 2_000_000


class TestEmailSendSerializer(serializers.Serializer):
    to = serializers.EmailField()
    subject = serializers.CharField(max_length=998)
    html = serializers.CharField(
        trim_whitespace=False,
        max_length=MAX_TEST_HTML_CHARS,
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
