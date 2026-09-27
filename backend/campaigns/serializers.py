from rest_framework import serializers

from email_generation.schemas import EmailDesign

from .models import (
    Campaign,
    CampaignDesignVersion,
    CampaignReferenceMode,
    CampaignStatus,
)


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



class CampaignDesignVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignDesignVersion
        fields = [
            "id",
            "version",
            "source",
            "email_design",
            "created_at",
        ]
        read_only_fields = fields


class CampaignCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = [
            "title",
            "source_url",
            "reference_mode",
            "additional_instructions",
        ]

    def validate_reference_mode(self, value):
        if value not in CampaignReferenceMode.values:
            raise serializers.ValidationError("Invalid reference mode.")
        return value


class CampaignUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = [
            "title",
            "source_url",
            "reference_mode",
            "additional_instructions",
        ]
        extra_kwargs = {
            "source_url": {"required": False},
            "reference_mode": {"required": False},
        }

    def validate(self, attrs):
        campaign = self.instance

        protected_fields = {
            "status",
            "active_design",
            "audience_selection",
            "audience_snapshot_id",
            "send_mode",
            "scheduled_for",
        }
        attempted_protected = protected_fields.intersection(
            self.initial_data.keys()
        )
        if attempted_protected:
            raise serializers.ValidationError(
                {
                    field: "This field is managed by campaign orchestration."
                    for field in sorted(attempted_protected)
                }
            )

        if campaign and campaign.status != CampaignStatus.DRAFT:
            locked_fields = {
                "source_url",
                "reference_mode",
                "additional_instructions",
            }
            changed_locked_fields = locked_fields.intersection(attrs)
            if changed_locked_fields:
                raise serializers.ValidationError(
                    {
                        field: (
                            "This generation input can only be changed while "
                            "the campaign is in draft status."
                        )
                        for field in changed_locked_fields
                    }
                )

        return attrs


class CampaignSerializer(serializers.ModelSerializer):
    active_design = CampaignDesignVersionSerializer(read_only=True)
    owner_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Campaign
        fields = [
            "id",
            "owner_id",
            "title",
            "status",
            "source_url",
            "reference_mode",
            "additional_instructions",
            "campaign_brief",
            "brand_profile",
            "reference",
            "content_plan",
            "fact_ledger",
            "asset_inventory",
            "active_design",
            "audience_selection",
            "audience_snapshot_id",
            "send_mode",
            "scheduled_for",
            "generated_at",
            "reviewed_at",
            "test_sent_at",
            "ready_at",
            "sending_at",
            "sent_at",
            "failed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CampaignTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[
            CampaignStatus.REVIEWED,
            CampaignStatus.READY,
        ]
    )


class CampaignGenerateSerializer(serializers.Serializer):
    reference_image = serializers.ImageField(
        required=False,
        allow_null=True,
    )

    def validate(self, attrs):
        campaign = self.context["campaign"]
        reference_image = attrs.get("reference_image")

        if (
            campaign.reference_mode == CampaignReferenceMode.UPLOADED
            and reference_image is None
        ):
            raise serializers.ValidationError(
                {
                    "reference_image": (
                        "A reference image is required when reference_mode "
                        "is uploaded."
                    )
                }
            )

        return attrs



class CampaignDesignSaveSerializer(serializers.Serializer):
    email_design = serializers.JSONField()

    def validate_email_design(self, value):
        try:
            design = EmailDesign.model_validate(value)
        except Exception as exc:
            raise serializers.ValidationError(
                f"Invalid EmailDesign: {exc}"
            ) from exc

        return design.model_dump(mode="json")


class CampaignTestSendSerializer(serializers.Serializer):
    to = serializers.EmailField()
    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=256,
    )


class CampaignRenderResponseSerializer(serializers.Serializer):
    html = serializers.CharField()
    mjml = serializers.CharField()
    compiler_errors = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
    )
    resolved_theme = serializers.JSONField()
    rendered_sections = serializers.IntegerField()
    available_asset_ids = serializers.ListField(
        child=serializers.CharField(),
    )



class CampaignRevisionSerializer(serializers.Serializer):
    instruction = serializers.CharField(
        min_length=1,
        max_length=2000,
        trim_whitespace=True,
    )


class CampaignAudienceResolveSerializer(serializers.Serializer):
    selection = serializers.JSONField()


class CampaignDeliveryRequestSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=256,
    )


class CampaignScheduleRequestSerializer(
    CampaignDeliveryRequestSerializer
):
    scheduled_for = serializers.DateTimeField()
