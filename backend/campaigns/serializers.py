from rest_framework import serializers


CAMPAIGN_TYPES = [
    "product_launch",
    "promotion",
    "seasonal",
    "newsletter",
    "announcement",
    "event",
    "educational",
    "reengagement",
    "other",
]

CAMPAIGN_GOALS = [
    "drive_sales",
    "product_discovery",
    "drive_traffic",
    "brand_awareness",
    "engagement",
    "retention",
    "registration",
    "other",
]

OFFER_TYPES = [
    "none",
    "percentage_discount",
    "fixed_discount",
    "free_shipping",
    "bundle",
    "gift",
    "other",
]


class AudienceSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=500)


class OfferSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=OFFER_TYPES, default="none")
    value = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=100,
    )
    code = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=100,
    )
    details = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=500,
    )


class ProductSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=300)
    url = serializers.URLField(required=False, allow_null=True)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=1000,
    )


class CampaignBriefSerializer(serializers.Serializer):
    schema_version = serializers.CharField(read_only=True, default="1.0")
    campaign_type = serializers.ChoiceField(choices=CAMPAIGN_TYPES)
    goal = serializers.ChoiceField(choices=CAMPAIGN_GOALS)
    audience = AudienceSerializer()
    offer = OfferSerializer(required=False)
    product = ProductSerializer(required=False, allow_null=True)
    destination_url = serializers.URLField(required=False, allow_null=True)
    tone_override = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=300,
    )
    additional_instructions = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=2000,
    )

    def validate(self, attrs):
        if attrs["campaign_type"] == "product_launch" and not attrs.get("product"):
            raise serializers.ValidationError(
                {"product": "Product is required for a product launch campaign."}
            )
        return attrs
