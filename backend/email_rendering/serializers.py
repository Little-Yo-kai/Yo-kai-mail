from rest_framework import serializers


class MJMLRenderRequestSerializer(serializers.Serializer):
    brand_profile = serializers.DictField()
    email_design = serializers.DictField()
    asset_inventory = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
    )
