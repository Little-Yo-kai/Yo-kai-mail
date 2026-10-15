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
    include_diagnostics = serializers.BooleanField(
        required=False,
        default=False,
    )


class DesignRevisionRequestSerializer(serializers.Serializer):
    brand_profile = serializers.DictField()
    email_design = serializers.DictField()
    reference_design_spec = serializers.DictField()
    content_plan = serializers.DictField()
    fact_ledger = serializers.DictField()
    asset_inventory = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
    )
    design_critique = serializers.DictField(
        required=False,
        allow_null=True,
    )
    max_revision_attempts = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=2,
    )
    include_diagnostics = serializers.BooleanField(
        required=False,
        default=False,
    )
