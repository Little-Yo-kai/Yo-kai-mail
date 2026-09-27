from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .contracts import CampaignGatewayExecutionError
from .integration_services import (
    CampaignIntegrationError,
    apply_campaign_delivery_state,
    get_campaign_delivery_summary,
    promote_campaign_assets,
    queue_campaign_delivery,
    resolve_campaign_audience,
    revise_campaign_design,
)
from .models import (
    Campaign,
    CampaignDesignVersion,
    CampaignSendMode,
    CampaignStatus,
)
from .services import send_campaign_test, transition_campaign


def sample_brand_profile():
    return {
        "schema_version": "1.0",
        "identity": {
            "name": "Example",
            "description": "Example brand",
            "industry": "Retail",
        },
        "visual": {
            "color_scheme": "light",
            "colors": {
                "primary": "#111111",
                "secondary": "#777777",
                "accent": "#111111",
                "background": "#FFFFFF",
                "text_primary": "#111111",
            },
            "typography": {
                "heading_family": "Arial",
                "body_family": "Arial",
            },
            "style_keywords": ["minimal"],
            "border_radius": None,
        },
        "communication": {
            "tone": ["clear"],
            "copy_characteristics": {
                "sentence_length": "short",
                "emoji_usage": "none",
                "formality": "medium",
            },
        },
        "assets": {
            "primary_logo": None,
            "hero_candidates": [],
            "og_image": None,
            "favicon": None,
        },
        "confidence": 1.0,
    }


def sample_email_design(*, subject="Campaign subject", asset_ids=None):
    return {
        "schema_version": "1.0",
        "subject": subject,
        "preheader": "Campaign preview",
        "theme": {
            "content_width": "standard",
            "heading_font_role": "brand_heading",
            "body_font_role": "brand_body",
            "primary_color_role": "primary",
            "background_color_role": "background",
            "button_color_role": "primary",
        },
        "sections": [
            {
                "id": "hero",
                "order": 1,
                "type": "hero",
                "layout": "centered",
                "eyebrow": "EXAMPLE",
                "headline": "A campaign",
                "body": "Persisted campaign copy.",
                "asset_ids": asset_ids or [],
                "items": [],
                "cta": None,
                "style": {
                    "alignment": "center",
                    "spacing": "balanced",
                    "background_role": "brand_background",
                },
            }
        ],
    }


class FakeAssetGateway:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def promote_campaign_assets(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeRevisionGateway:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def revise_campaign_design(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeAudienceGateway:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def resolve_campaign_audience(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeDeliveryGateway:
    def __init__(self, *, job=None, summary=None):
        self.job = job
        self.summary = summary
        self.create_calls = []
        self.summary_calls = []

    def create_campaign_delivery(self, **kwargs):
        self.create_calls.append(kwargs)
        return self.job

    def get_campaign_delivery_summary(self, **kwargs):
        self.summary_calls.append(kwargs)
        return self.summary


class ConfiguredAudienceGateway:
    def resolve_campaign_audience(self, **kwargs):
        return {
            "snapshot_id": str(uuid4()),
            "recipient_count": 12,
            "excluded_count": 1,
            "selection": kwargs["selection"],
        }


class RateLimitedAudienceGateway:
    def resolve_campaign_audience(self, **kwargs):
        raise CampaignGatewayExecutionError(
            "Audience provider rate limited the request.",
            retryable=True,
            status_code=429,
        )


class CampaignIntegrationContractTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="test-pass-123",
        )

    def create_campaign(
        self,
        *,
        status=CampaignStatus.GENERATED,
        email_design=None,
        asset_inventory=None,
    ):
        campaign = Campaign.objects.create(
            owner=self.user,
            title="Integrated campaign",
            source_url="https://example.com",
            status=status,
            brand_profile=sample_brand_profile(),
            campaign_brief={"schema_version": "1.0"},
            reference={"source": "internal_library"},
            content_plan={"schema_version": "1.0"},
            fact_ledger={"verified_facts": ["Brand: Example"]},
            asset_inventory=asset_inventory or [],
        )
        version = CampaignDesignVersion.objects.create(
            campaign=campaign,
            version=1,
            source="generated",
            email_design=email_design or sample_email_design(),
            created_by=self.user,
        )
        campaign.active_design = version
        campaign.save(update_fields=["active_design", "updated_at"])
        return campaign

    def test_asset_gateway_promotes_only_assets_used_by_active_design(self):
        campaign = self.create_campaign(
            email_design=sample_email_design(asset_ids=["hero_1"]),
            asset_inventory=[
                {
                    "asset_id": "hero_1",
                    "kind": "hero",
                    "url": "https://source.example/hero.jpg",
                    "source": "request",
                },
                {
                    "asset_id": "unused",
                    "kind": "detail",
                    "url": "https://source.example/detail.jpg",
                    "source": "request",
                },
            ],
        )
        gateway = FakeAssetGateway(
            {
                "assets": [
                    {
                        "asset_id": "hero_1",
                        "asset_record_id": str(uuid4()),
                        "kind": "hero",
                        "public_url": "https://assets.example/hero.jpg",
                    }
                ],
                "unresolved_asset_ids": [],
            }
        )

        result = promote_campaign_assets(campaign, gateway=gateway)

        campaign.refresh_from_db()
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(
            [item["asset_id"] for item in gateway.calls[0]["assets"]],
            ["hero_1"],
        )
        self.assertEqual(result.assets[0].asset_id, "hero_1")
        self.assertEqual(
            campaign.asset_inventory[0]["url"],
            "https://assets.example/hero.jpg",
        )
        self.assertEqual(
            campaign.asset_inventory[0]["source"],
            "asset_library",
        )
        self.assertTrue(
            campaign.asset_inventory[0].get("asset_record_id")
        )
        self.assertEqual(
            campaign.asset_inventory[1]["url"],
            "https://source.example/detail.jpg",
        )

    def test_asset_promotion_is_frozen_after_delivery_starts(self):
        campaign = self.create_campaign(
            status=CampaignStatus.SENDING,
            email_design=sample_email_design(asset_ids=["hero_1"]),
            asset_inventory=[
                {
                    "asset_id": "hero_1",
                    "kind": "hero",
                    "url": "https://assets.example/hero.jpg",
                    "source": "asset_library",
                }
            ],
        )

        with self.assertRaises(CampaignIntegrationError):
            promote_campaign_assets(
                campaign,
                gateway=FakeAssetGateway(
                    {
                        "assets": [],
                        "unresolved_asset_ids": [],
                    }
                ),
            )

    def test_asset_promotion_rejects_partial_required_result(self):
        campaign = self.create_campaign(
            email_design=sample_email_design(asset_ids=["hero_1"]),
            asset_inventory=[
                {
                    "asset_id": "hero_1",
                    "kind": "hero",
                    "url": "https://source.example/hero.jpg",
                    "source": "request",
                }
            ],
        )
        gateway = FakeAssetGateway(
            {
                "assets": [],
                "unresolved_asset_ids": ["hero_1"],
            }
        )

        with self.assertRaises(CampaignIntegrationError):
            promote_campaign_assets(campaign, gateway=gateway)

    def test_revision_gateway_creates_revision_version_and_resets_state(self):
        campaign = self.create_campaign(status=CampaignStatus.READY)
        campaign.reviewed_at = timezone.now()
        campaign.test_sent_at = timezone.now()
        campaign.ready_at = timezone.now()
        campaign.save(
            update_fields=[
                "reviewed_at",
                "test_sent_at",
                "ready_at",
                "updated_at",
            ]
        )
        gateway = FakeRevisionGateway(
            {
                "email_design": sample_email_design(
                    subject="Revised subject"
                ),
                "revision_notes": ["Shortened the headline."],
            }
        )

        version, result = revise_campaign_design(
            campaign,
            gateway=gateway,
            instruction="Make it shorter.",
            user=self.user,
        )

        campaign.refresh_from_db()
        self.assertEqual(version.version, 2)
        self.assertEqual(version.source, "revision")
        self.assertEqual(
            result.email_design.subject,
            "Revised subject",
        )
        self.assertEqual(campaign.status, CampaignStatus.GENERATED)
        self.assertIsNone(campaign.reviewed_at)
        self.assertIsNone(campaign.test_sent_at)
        self.assertIsNone(campaign.ready_at)

    def test_audience_resolution_persists_immutable_snapshot_reference(self):
        campaign = self.create_campaign(status=CampaignStatus.READY)
        snapshot_id = uuid4()
        gateway = FakeAudienceGateway(
            {
                "snapshot_id": str(snapshot_id),
                "recipient_count": 125,
                "excluded_count": 5,
                "selection": {"list_ids": ["customers"]},
            }
        )

        result = resolve_campaign_audience(
            campaign,
            gateway=gateway,
            selection={"list_ids": ["customers"]},
        )

        campaign.refresh_from_db()
        self.assertEqual(result.recipient_count, 125)
        self.assertEqual(campaign.audience_snapshot_id, snapshot_id)
        self.assertEqual(
            campaign.audience_selection,
            {"list_ids": ["customers"]},
        )

    def test_empty_audience_snapshot_is_rejected(self):
        campaign = self.create_campaign(status=CampaignStatus.READY)
        gateway = FakeAudienceGateway(
            {
                "snapshot_id": str(uuid4()),
                "recipient_count": 0,
                "excluded_count": 0,
                "selection": {},
            }
        )

        with self.assertRaises(CampaignIntegrationError):
            resolve_campaign_audience(
                campaign,
                gateway=gateway,
                selection={},
            )

    @patch("campaigns.integration_services.render_campaign_email")
    def test_final_delivery_rejects_unpromoted_required_assets(
        self,
        render_mock,
    ):
        campaign = self.create_campaign(
            status=CampaignStatus.READY,
            email_design=sample_email_design(asset_ids=["hero_1"]),
            asset_inventory=[
                {
                    "asset_id": "hero_1",
                    "kind": "hero",
                    "url": "https://source.example/hero.jpg",
                    "source": "request",
                }
            ],
        )
        campaign.audience_snapshot_id = uuid4()
        campaign.save(
            update_fields=["audience_snapshot_id", "updated_at"]
        )

        with self.assertRaises(CampaignIntegrationError):
            queue_campaign_delivery(
                campaign,
                gateway=FakeDeliveryGateway(
                    job={
                        "job_id": "should-not-run",
                        "mode": "send_now",
                        "status": "queued",
                        "scheduled_for": None,
                    }
                ),
                mode=CampaignSendMode.SEND_NOW,
            )

        render_mock.assert_not_called()

    @patch("campaigns.integration_services.render_campaign_email")
    def test_send_now_contract_moves_ready_campaign_to_sending(
        self,
        render_mock,
    ):
        campaign = self.create_campaign(status=CampaignStatus.READY)
        campaign.audience_snapshot_id = uuid4()
        campaign.save(
            update_fields=["audience_snapshot_id", "updated_at"]
        )
        render_mock.return_value = {
            "html": "<html>Final campaign</html>",
        }
        gateway = FakeDeliveryGateway(
            job={
                "job_id": "job-123",
                "mode": "send_now",
                "status": "queued",
                "scheduled_for": None,
            }
        )

        result = queue_campaign_delivery(
            campaign,
            gateway=gateway,
            mode=CampaignSendMode.SEND_NOW,
        )

        campaign.refresh_from_db()
        self.assertEqual(result.job_id, "job-123")
        self.assertEqual(campaign.status, CampaignStatus.SENDING)
        self.assertEqual(campaign.send_mode, CampaignSendMode.SEND_NOW)
        self.assertIsNone(campaign.scheduled_for)
        self.assertEqual(
            gateway.create_calls[0]["audience_snapshot_id"],
            campaign.audience_snapshot_id,
        )
        self.assertTrue(
            gateway.create_calls[0]["idempotency_key"].startswith(
                "campaign-"
            )
        )

    @patch("campaigns.integration_services.render_campaign_email")
    def test_scheduled_contract_moves_ready_campaign_to_scheduled(
        self,
        render_mock,
    ):
        campaign = self.create_campaign(status=CampaignStatus.READY)
        campaign.audience_snapshot_id = uuid4()
        campaign.save(
            update_fields=["audience_snapshot_id", "updated_at"]
        )
        scheduled_for = timezone.now() + timedelta(hours=2)
        render_mock.return_value = {
            "html": "<html>Final campaign</html>",
        }
        gateway = FakeDeliveryGateway(
            job={
                "job_id": "job-456",
                "mode": "scheduled",
                "status": "scheduled",
                "scheduled_for": scheduled_for.isoformat(),
            }
        )

        result = queue_campaign_delivery(
            campaign,
            gateway=gateway,
            mode=CampaignSendMode.SCHEDULED,
            scheduled_for=scheduled_for,
        )

        campaign.refresh_from_db()
        self.assertEqual(result.job_id, "job-456")
        self.assertEqual(campaign.status, CampaignStatus.SCHEDULED)
        self.assertEqual(campaign.send_mode, CampaignSendMode.SCHEDULED)
        self.assertEqual(campaign.scheduled_for, scheduled_for)

    def test_delivery_state_updates_move_scheduled_to_sent(self):
        campaign = self.create_campaign(status=CampaignStatus.SCHEDULED)
        campaign.audience_snapshot_id = uuid4()
        campaign.send_mode = CampaignSendMode.SCHEDULED
        campaign.scheduled_for = timezone.now() + timedelta(hours=1)
        campaign.save(
            update_fields=[
                "audience_snapshot_id",
                "send_mode",
                "scheduled_for",
                "updated_at",
            ]
        )

        apply_campaign_delivery_state(
            campaign,
            update={
                "job_id": "job-789",
                "status": "sending",
            },
        )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, CampaignStatus.SENDING)
        self.assertIsNotNone(campaign.sending_at)

        apply_campaign_delivery_state(
            campaign,
            update={
                "job_id": "job-789",
                "status": "sent",
            },
        )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, CampaignStatus.SENT)
        self.assertIsNotNone(campaign.sent_at)

    def test_delivery_state_rejects_impossible_sent_transition(self):
        campaign = self.create_campaign(status=CampaignStatus.READY)

        with self.assertRaises(CampaignIntegrationError):
            apply_campaign_delivery_state(
                campaign,
                update={
                    "job_id": "job-invalid",
                    "status": "sent",
                },
            )

    @patch("campaigns.integration_services.render_campaign_email")
    @patch("campaigns.services.ResendEmailService.send_test_email")
    @patch("campaigns.services.compile_mjml_to_html")
    def test_contract_level_full_campaign_flow_reaches_sent(
        self,
        compile_mock,
        test_send_mock,
        final_render_mock,
    ):
        campaign = self.create_campaign(
            status=CampaignStatus.GENERATED
        )

        compile_mock.return_value = {
            "html": "<html>Test email</html>",
            "compiler_errors": [],
        }
        test_send_mock.return_value = {
            "email_id": "test-email-1",
            "provider": "resend",
            "to": "owner@example.com",
            "from": "Yo-kai Mail <test@example.com>",
            "idempotency_key": "test-send",
            "inline_assets": [],
            "inline_asset_count": 0,
            "inline_asset_bytes": 0,
        }

        send_campaign_test(
            campaign,
            to="owner@example.com",
        )
        campaign.refresh_from_db()
        self.assertEqual(
            campaign.status,
            CampaignStatus.TEST_SENT,
        )

        transition_campaign(
            campaign,
            next_status=CampaignStatus.READY,
        )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, CampaignStatus.READY)

        resolve_campaign_audience(
            campaign,
            gateway=FakeAudienceGateway(
                {
                    "snapshot_id": str(uuid4()),
                    "recipient_count": 20,
                    "excluded_count": 2,
                    "selection": {"list_ids": ["customers"]},
                }
            ),
            selection={"list_ids": ["customers"]},
        )
        campaign.refresh_from_db()
        self.assertIsNotNone(campaign.audience_snapshot_id)

        final_render_mock.return_value = {
            "html": "<html>Final email</html>",
        }
        delivery_gateway = FakeDeliveryGateway(
            job={
                "job_id": "delivery-job-1",
                "mode": "send_now",
                "status": "queued",
                "scheduled_for": None,
            }
        )
        queue_campaign_delivery(
            campaign,
            gateway=delivery_gateway,
            mode=CampaignSendMode.SEND_NOW,
        )
        campaign.refresh_from_db()
        self.assertEqual(
            campaign.status,
            CampaignStatus.SENDING,
        )

        apply_campaign_delivery_state(
            campaign,
            update={
                "job_id": "delivery-job-1",
                "status": "sent",
            },
        )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, CampaignStatus.SENT)
        self.assertIsNotNone(campaign.sent_at)

    def test_delivery_summary_contract_is_provider_independent(self):
        campaign = self.create_campaign(status=CampaignStatus.SENDING)
        gateway = FakeDeliveryGateway(
            summary={
                "total": 100,
                "queued": 0,
                "sent": 100,
                "delivered": 93,
                "bounced": 4,
                "complained": 1,
                "failed": 2,
                "last_event_at": timezone.now().isoformat(),
            }
        )

        result = get_campaign_delivery_summary(
            campaign,
            gateway=gateway,
        )

        self.assertEqual(result.total, 100)
        self.assertEqual(result.delivered, 93)
        self.assertEqual(result.bounced, 4)
        self.assertEqual(
            gateway.summary_calls[0]["campaign_id"],
            campaign.id,
        )



class CampaignIntegrationApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="api-owner",
            email="api-owner@example.com",
            password="test-pass-123",
        )
        self.other = user_model.objects.create_user(
            username="api-other",
            email="api-other@example.com",
            password="test-pass-123",
        )
        self.client.force_authenticate(user=self.owner)

    def create_campaign(self, *, owner=None, status_value="generated"):
        campaign = Campaign.objects.create(
            owner=owner or self.owner,
            title="API campaign",
            source_url="https://example.com",
            status=status_value,
            brand_profile=sample_brand_profile(),
            asset_inventory=[],
        )
        version = CampaignDesignVersion.objects.create(
            campaign=campaign,
            version=1,
            source="generated",
            email_design=sample_email_design(),
            created_by=owner or self.owner,
        )
        campaign.active_design = version
        campaign.save(update_fields=["active_design", "updated_at"])
        return campaign

    @override_settings(
        CAMPAIGN_AUDIENCE_GATEWAY=(
            "campaigns.test_integrations.ConfiguredAudienceGateway"
        )
    )
    def test_configured_gateway_loads_through_public_route(self):
        campaign = self.create_campaign(status_value="ready")

        response = self.client.post(
            reverse(
                "campaign-audience-resolve",
                kwargs={"campaign_id": campaign.id},
            ),
            {"selection": {"list_ids": ["customers"]}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        campaign.refresh_from_db()
        self.assertIsNotNone(campaign.audience_snapshot_id)
        self.assertEqual(
            campaign.audience_selection,
            {"list_ids": ["customers"]},
        )

    @override_settings(
        CAMPAIGN_AUDIENCE_GATEWAY=(
            "campaigns.test_integrations.RateLimitedAudienceGateway"
        )
    )
    def test_gateway_rate_limit_maps_to_429(self):
        campaign = self.create_campaign(status_value="ready")

        response = self.client.post(
            reverse(
                "campaign-audience-resolve",
                kwargs={"campaign_id": campaign.id},
            ),
            {"selection": {"list_ids": ["customers"]}},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
        self.assertTrue(response.data["retryable"])

    @override_settings(CAMPAIGN_ASSET_PROMOTION_GATEWAY="")
    def test_unconfigured_teammate_gateway_returns_503(self):
        campaign = self.create_campaign()

        response = self.client.post(
            reverse(
                "campaign-assets-promote",
                kwargs={"campaign_id": campaign.id},
            ),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    def test_integration_route_is_owner_scoped(self):
        campaign = self.create_campaign(owner=self.other)

        response = self.client.post(
            reverse(
                "campaign-revision",
                kwargs={"campaign_id": campaign.id},
            ),
            {"instruction": "Shorten it."},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_public_transition_api_cannot_fake_system_delivery_state(self):
        campaign = self.create_campaign()

        response = self.client.post(
            reverse(
                "campaign-transition",
                kwargs={"campaign_id": campaign.id},
            ),
            {"status": "sending"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_ready_transition_requires_successful_test_send(self):
        campaign = self.create_campaign(status_value="reviewed")

        response = self.client.post(
            reverse(
                "campaign-transition",
                kwargs={"campaign_id": campaign.id},
            ),
            {"status": "ready"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, CampaignStatus.REVIEWED)

    def test_patch_cannot_set_internal_audience_or_delivery_fields(self):
        campaign = self.create_campaign()
        fake_snapshot = uuid4()

        response = self.client.patch(
            reverse(
                "campaign-detail",
                kwargs={"campaign_id": campaign.id},
            ),
            {
                "title": "Safe title update",
                "audience_snapshot_id": str(fake_snapshot),
                "send_mode": "send_now",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        campaign.refresh_from_db()
        self.assertEqual(campaign.title, "Safe title update")
        self.assertIsNone(campaign.audience_snapshot_id)
        self.assertEqual(campaign.send_mode, "none")
