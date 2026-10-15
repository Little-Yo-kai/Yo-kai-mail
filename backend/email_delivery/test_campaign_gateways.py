from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from campaigns.contracts import CampaignGatewayExecutionError
from campaigns.integration_services import CampaignIntegrationError
from campaigns.models import Campaign, CampaignStatus

from .campaign_gateway import ContactsAudienceGateway, ResendCampaignDeliveryGateway
from .models import (
    CampaignSendJob,
    ConsentStatus,
    Contact,
    ContactStatus,
    DeliveryRecord,
)


class CampaignGatewayIntegrationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="recipient-owner",
            email="owner@example.com",
            password="not-a-secret",
        )
        self.other = get_user_model().objects.create_user(
            username="recipient-other",
            email="other@example.com",
            password="not-a-secret",
        )
        self.campaign = Campaign.objects.create(
            owner=self.owner,
            source_url="https://example.com",
            status=CampaignStatus.READY,
        )
        self.contact = Contact.objects.create(
            owner=self.owner,
            email="eligible@example.com",
            status=ContactStatus.ACTIVE,
            consent_status=ConsentStatus.GRANTED,
            consented_at=timezone.now(),
        )

    def test_empty_selection_cannot_expand_to_all_contacts(self):
        with self.assertRaises(CampaignIntegrationError):
            ContactsAudienceGateway().resolve_campaign_audience(
                campaign_id=self.campaign.id,
                owner_id=self.owner.id,
                selection={},
            )

    def test_audience_snapshot_only_contains_explicit_eligible_recipient(self):
        Contact.objects.create(
            owner=self.owner,
            email="unconsented@example.com",
        )
        result = ContactsAudienceGateway().resolve_campaign_audience(
            campaign_id=self.campaign.id,
            owner_id=self.owner.id,
            selection={"contact_ids": [str(self.contact.id)]},
        )
        self.assertEqual(result["recipient_count"], 1)
        self.campaign.refresh_from_db()
        self.assertIsNone(self.campaign.audience_snapshot_id)
        self.assertTrue(result["snapshot_id"])

    @override_settings(RESEND_CAMPAIGN_SEND_ENABLED=True)
    @patch("email_delivery.campaign_gateway.dispatch_campaign_send_job")
    def test_delivery_gateway_creates_job_and_recipient_records(self, dispatch):
        snapshot = ContactsAudienceGateway().resolve_campaign_audience(
            campaign_id=self.campaign.id,
            owner_id=self.owner.id,
            selection={"contact_ids": [str(self.contact.id)]},
        )
        self.campaign.status = CampaignStatus.SENDING
        self.campaign.send_mode = "send_now"
        self.campaign.save(update_fields=["status", "send_mode", "updated_at"])

        result = ResendCampaignDeliveryGateway().create_campaign_delivery(
            campaign_id=self.campaign.id,
            audience_snapshot_id=snapshot["snapshot_id"],
            subject="Verified test",
            html="<html><body>Hello</body></html>",
            mode="send_now",
            scheduled_for=None,
            idempotency_key="idempotency-test-1",
        )
        self.assertEqual(result["status"], "queued")
        self.assertEqual(CampaignSendJob.objects.filter(campaign=self.campaign).count(), 1)
        self.assertEqual(DeliveryRecord.objects.filter(campaign=self.campaign).count(), 1)
        dispatch.assert_called_once()

        summary = ResendCampaignDeliveryGateway().get_campaign_delivery_summary(
            campaign_id=self.campaign.id,
        )
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["queued"], 1)

    @override_settings(RESEND_CAMPAIGN_SEND_ENABLED=False)
    def test_campaign_delivery_is_disabled_until_explicitly_enabled(self):
        with self.assertRaises(CampaignGatewayExecutionError):
            ResendCampaignDeliveryGateway().create_campaign_delivery(
                campaign_id=self.campaign.id,
                audience_snapshot_id=uuid4(),
                subject="Blocked",
                html="<html></html>",
                mode="send_now",
                scheduled_for=None,
                idempotency_key="blocked",
            )
