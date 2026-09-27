from rest_framework import serializers


class DesignCritiqueRequestSerializer(serializers.Serializer):
    brand_profile = serializers.DictField()
    email_design = serializers.DictField()
    reference_design_spec = serializers.DictField()
    asset_inventory = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
    )
