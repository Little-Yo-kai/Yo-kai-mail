from rest_framework import serializers


class ReferenceSelectionRequestSerializer(serializers.Serializer):
    brand_profile = serializers.DictField()
    campaign_brief = serializers.DictField()

    def validate_brand_profile(self, value):
        identity = value.get("identity")
        if not isinstance(identity, dict):
            raise serializers.ValidationError(
                "BrandProfile must contain an identity object."
            )
        return value

    def validate_campaign_brief(self, value):
        if not value.get("campaign_type"):
            raise serializers.ValidationError(
                "CampaignBrief must contain campaign_type."
            )
        if not value.get("goal"):
            raise serializers.ValidationError(
                "CampaignBrief must contain goal."
            )
        return value
