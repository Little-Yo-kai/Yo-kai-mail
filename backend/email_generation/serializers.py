from rest_framework import serializers


class ContentPlanRequestSerializer(serializers.Serializer):
    brand_profile = serializers.DictField()
    campaign_brief = serializers.DictField()
    reference_design_spec = serializers.DictField()
    available_assets = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
    )

    def validate_brand_profile(self, value):
        if not isinstance(value.get("identity"), dict):
            raise serializers.ValidationError(
                "BrandProfile must contain an identity object."
            )
        if not isinstance(value.get("communication"), dict):
            raise serializers.ValidationError(
                "BrandProfile must contain a communication object."
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

    def validate_reference_design_spec(self, value):
        if not value.get("archetype"):
            raise serializers.ValidationError(
                "ReferenceDesignSpec must contain archetype."
            )
        if not isinstance(value.get("section_sequence"), list):
            raise serializers.ValidationError(
                "ReferenceDesignSpec must contain section_sequence."
            )
        return value
