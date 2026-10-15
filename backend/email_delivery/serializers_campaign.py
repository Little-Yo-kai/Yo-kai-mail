from rest_framework import serializers

from .models import (
    ConsentStatus,
    Contact,
    ContactList,
    ContactStatus,
)


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            "id",
            "email",
            "normalized_email",
            "first_name",
            "last_name",
            "display_name",
            "status",
            "consent_status",
            "consent_source",
            "consented_at",
            "source",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "normalized_email",
            "created_at",
            "updated_at",
        ]


class ContactUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            "first_name",
            "last_name",
            "display_name",
            "status",
            "consent_status",
            "consent_source",
            "consented_at",
            "source",
            "metadata",
        ]

    def validate(self, attrs):
        contact = self.instance
        next_status = attrs.get("status", contact.status)
        next_consent = attrs.get("consent_status", contact.consent_status)

        if (
            next_status == ContactStatus.ACTIVE
            and next_consent != ConsentStatus.GRANTED
        ):
            raise serializers.ValidationError(
                {
                    "status": (
                        "A contact must have confirmed consent before being "
                        "marked active."
                    )
                }
            )

        if next_status in {
            ContactStatus.UNSUBSCRIBED,
            ContactStatus.BOUNCED,
            ContactStatus.SUPPRESSED,
            ContactStatus.COMPLAINED,
        }:
            attrs["consent_status"] = ConsentStatus.WITHDRAWN

        if (
            next_consent == ConsentStatus.GRANTED
            and "consented_at" not in attrs
            and contact.consented_at is None
        ):
            raise serializers.ValidationError(
                {
                    "consented_at": (
                        "Record when consent was granted before enabling a contact."
                    )
                }
            )

        return attrs


class ContactListSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = ContactList
        fields = [
            "id",
            "name",
            "description",
            "member_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "member_count", "created_at", "updated_at"]

    def get_member_count(self, contact_list):
        return contact_list.memberships.count()


class ContactListMembersSerializer(serializers.Serializer):
    contact_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=10000,
    )


class ContactImportSerializer(serializers.Serializer):
    file = serializers.FileField()
    list_id = serializers.UUIDField(required=False)

    def validate_file(self, value):
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("CSV files must be 5 MB or smaller.")
        return value


class ResolveAudienceSerializer(serializers.Serializer):
    list_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        max_length=500,
    )
    contact_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        max_length=10000,
    )

    def validate(self, attrs):
        if not attrs.get("list_ids") and not attrs.get("contact_ids"):
            raise serializers.ValidationError(
                "Choose at least one contact list or contact."
            )
        attrs["list_ids"] = list(dict.fromkeys(attrs.get("list_ids", [])))
        attrs["contact_ids"] = list(
            dict.fromkeys(attrs.get("contact_ids", []))
        )
        return attrs


class ScheduleCampaignSerializer(serializers.Serializer):
    scheduled_for = serializers.DateTimeField()

    def validate_scheduled_for(self, value):
        from django.utils import timezone

        if value <= timezone.now():
            raise serializers.ValidationError(
                "Choose a future time to schedule this campaign."
            )
        return value
