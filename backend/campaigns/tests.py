from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from unittest.mock import patch
from rest_framework import status
from rest_framework.test import APITestCase


def sample_persisted_brand_profile():
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


def sample_persisted_email_design(subject="Campaign subject"):
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
                "headline": "A persisted campaign",
                "body": "Rendered from campaign state.",
                "asset_ids": [],
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


class CampaignBriefViewTests(APITestCase):
    def test_product_launch_returns_normalized_campaign_brief(self):
        payload = {
            "campaign_type": "product_launch",
            "goal": "drive_sales",
            "audience": {
                "description": "Existing luxury customers",
            },
            "product": {
                "name": "Speedy Bandouliere 20",
                "url": "https://example.com/products/speedy",
            },
            "destination_url": "https://example.com/products/speedy",
            "additional_instructions": "Keep the copy minimal and refined.",
        }

        response = self.client.post(
            reverse("campaign-brief"),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        brief = response.data["data"]
        self.assertEqual(brief["schema_version"], "1.0")
        self.assertEqual(brief["campaign_type"], "product_launch")
        self.assertEqual(brief["offer"]["type"], "none")
        self.assertIsNone(brief["tone_override"])

    def test_product_launch_requires_product(self):
        payload = {
            "campaign_type": "product_launch",
            "goal": "product_discovery",
            "audience": {
                "description": "Existing customers",
            },
        }

        response = self.client.post(
            reverse("campaign-brief"),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("product", response.data)

    def test_promotion_accepts_offer_without_product(self):
        payload = {
            "campaign_type": "promotion",
            "goal": "drive_sales",
            "audience": {
                "description": "Newsletter subscribers",
            },
            "offer": {
                "type": "percentage_discount",
                "value": "20%",
                "code": "SAVE20",
            },
        }

        response = self.client.post(
            reverse("campaign-brief"),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        brief = response.data["data"]
        self.assertEqual(brief["offer"]["value"], "20%")
        self.assertEqual(brief["offer"]["code"], "SAVE20")
        self.assertIsNone(brief["product"])



class CampaignPersistenceApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="test-pass-123",
        )
        self.other = user_model.objects.create_user(
            username="other",
            email="other@example.com",
            password="test-pass-123",
        )

    def _authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.owner)

    def _create_campaign(self, **overrides):
        from .models import Campaign

        values = {
            "owner": self.owner,
            "title": "Launch",
            "source_url": "https://example.com",
        }
        values.update(overrides)
        return Campaign.objects.create(**values)

    def test_create_campaign_draft_is_owned_by_current_user(self):
        self._authenticate()

        response = self.client.post(
            reverse("campaign-list-create"),
            {
                "title": "Autumn launch",
                "source_url": "https://example.com",
                "reference_mode": "automatic",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["status"], "draft")
        self.assertEqual(
            response.data["data"]["owner_id"],
            self.owner.id,
        )

    def test_list_and_detail_do_not_expose_another_users_campaign(self):
        self._authenticate()
        mine = self._create_campaign()
        self._create_campaign(
            owner=self.other,
            title="Private campaign",
        )

        list_response = self.client.get(
            reverse("campaign-list-create")
        )

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data["data"]), 1)
        self.assertEqual(
            str(list_response.data["data"][0]["id"]),
            str(mine.id),
        )

        detail_response = self.client.get(
            reverse(
                "campaign-detail",
                kwargs={"campaign_id": self._create_campaign(
                    owner=self.other,
                    title="Another private campaign",
                ).id},
            )
        )
        self.assertEqual(
            detail_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_invalid_transition_is_rejected(self):
        self._authenticate()
        campaign = self._create_campaign()

        response = self.client.post(
            reverse(
                "campaign-transition",
                kwargs={"campaign_id": campaign.id},
            ),
            {"status": "ready"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "draft")

    @patch("campaigns.services.generate_phase1_demo")
    def test_generate_persists_outputs_and_active_design(
        self,
        generate_mock,
    ):
        from .models import CampaignDesignVersion

        self._authenticate()
        campaign = self._create_campaign()

        generate_mock.return_value = {
            "campaign_brief": {
                "schema_version": "1.0",
                "campaign_type": "newsletter",
            },
            "brand_profile": {
                "schema_version": "1.0",
                "identity": {"name": "Example"},
            },
            "reference": {
                "source": "internal_library",
                "name": "Editorial",
            },
            "content_plan": {
                "schema_version": "1.0",
                "campaign_angle": "Introduce the brand",
            },
            "email_design": {
                "schema_version": "1.0",
                "subject": "Hello",
                "preheader": "Welcome",
                "theme": {},
                "sections": [],
            },
        }

        response = self.client.post(
            reverse(
                "campaign-generate",
                kwargs={"campaign_id": campaign.id},
            ),
            {},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "generated")
        self.assertIsNotNone(campaign.generated_at)
        self.assertIsNotNone(campaign.active_design_id)
        self.assertEqual(
            campaign.brand_profile["identity"]["name"],
            "Example",
        )
        self.assertEqual(
            CampaignDesignVersion.objects.filter(
                campaign=campaign
            ).count(),
            1,
        )
        self.assertEqual(
            campaign.active_design.email_design["subject"],
            "Hello",
        )

    @patch("campaigns.services.generate_phase1_demo")
    def test_regeneration_creates_new_design_version(
        self,
        generate_mock,
    ):
        self._authenticate()
        campaign = self._create_campaign()
        generate_mock.return_value = {
            "campaign_brief": {},
            "brand_profile": {},
            "reference": {},
            "content_plan": {},
            "email_design": {
                "schema_version": "1.0",
                "subject": "Version",
                "preheader": "Preview",
                "theme": {},
                "sections": [],
            },
        }

        url = reverse(
            "campaign-generate",
            kwargs={"campaign_id": campaign.id},
        )
        first = self.client.post(url, {}, format="multipart")
        second = self.client.post(url, {}, format="multipart")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)

        campaign.refresh_from_db()
        self.assertEqual(campaign.design_versions.count(), 2)
        self.assertEqual(campaign.active_design.version, 2)

    @patch("campaigns.services.generate_phase1_demo")
    def test_generation_rejects_stale_result_after_campaign_changes(
        self,
        generate_mock,
    ):
        self._authenticate()
        campaign = self._create_campaign()

        def generation_side_effect(**kwargs):
            from .models import Campaign

            Campaign.objects.filter(pk=campaign.pk).update(
                source_url="https://newer.example.com"
            )
            return {
                "campaign_brief": {},
                "brand_profile": {},
                "reference": {},
                "content_plan": {},
                "email_design": {
                    "schema_version": "1.0",
                    "subject": "Stale generation",
                    "preheader": "Preview",
                    "theme": {},
                    "sections": [],
                },
            }

        generate_mock.side_effect = generation_side_effect

        response = self.client.post(
            reverse(
                "campaign-generate",
                kwargs={"campaign_id": campaign.id},
            ),
            {},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "draft")
        self.assertIsNone(campaign.active_design_id)
        self.assertEqual(campaign.design_versions.count(), 0)

    @patch("campaigns.services.generate_phase1_demo")
    def test_generation_inputs_lock_after_campaign_is_generated(
        self,
        generate_mock,
    ):
        self._authenticate()
        campaign = self._create_campaign()
        generate_mock.return_value = {
            "campaign_brief": {},
            "brand_profile": {},
            "reference": {},
            "content_plan": {},
            "email_design": {
                "schema_version": "1.0",
                "subject": "Generated",
                "preheader": "Preview",
                "theme": {},
                "sections": [],
            },
        }

        self.client.post(
            reverse(
                "campaign-generate",
                kwargs={"campaign_id": campaign.id},
            ),
            {},
            format="multipart",
        )

        response = self.client.patch(
            reverse(
                "campaign-detail",
                kwargs={"campaign_id": campaign.id},
            ),
            {"source_url": "https://changed.example.com"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_campaign_endpoints_require_authentication(self):
        response = self.client.get(reverse("campaign-list-create"))
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )


    def _create_generated_campaign_with_design(self, *, status_value="generated"):
        from .models import CampaignDesignVersion

        campaign = self._create_campaign(
            status=status_value,
            brand_profile=sample_persisted_brand_profile(),
            asset_inventory=[],
            fact_ledger={"verified_facts": ["Brand: Example"]},
        )
        version = CampaignDesignVersion.objects.create(
            campaign=campaign,
            version=1,
            source="generated",
            email_design=sample_persisted_email_design(),
            created_by=self.owner,
        )
        campaign.active_design = version
        campaign.save(update_fields=["active_design", "updated_at"])
        return campaign

    def test_design_save_creates_new_version_and_invalidates_test_state(self):
        from django.utils import timezone

        self._authenticate()
        campaign = self._create_generated_campaign_with_design(
            status_value="test_sent"
        )
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

        edited = sample_persisted_email_design(
            subject="Edited campaign subject"
        )
        response = self.client.put(
            reverse(
                "campaign-design",
                kwargs={"campaign_id": campaign.id},
            ),
            {"email_design": edited},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "generated")
        self.assertEqual(campaign.design_versions.count(), 2)
        self.assertEqual(campaign.active_design.version, 2)
        self.assertEqual(campaign.active_design.source, "user_edit")
        self.assertEqual(
            campaign.active_design.email_design["subject"],
            "Edited campaign subject",
        )
        self.assertIsNone(campaign.reviewed_at)
        self.assertIsNone(campaign.test_sent_at)
        self.assertIsNone(campaign.ready_at)

    @patch("campaigns.services.compile_mjml_to_html")
    def test_campaign_render_uses_persisted_context(self, compile_mock):
        self._authenticate()
        campaign = self._create_generated_campaign_with_design()
        compile_mock.return_value = {
            "html": "<html><body>Rendered</body></html>",
            "compiler_errors": [],
        }

        response = self.client.get(
            reverse(
                "campaign-render",
                kwargs={"campaign_id": campaign.id},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["html"],
            "<html><body>Rendered</body></html>",
        )
        compiled_mjml = compile_mock.call_args.args[0]
        self.assertIn("<mjml>", compiled_mjml)
        self.assertIn("A persisted campaign", compiled_mjml)

    @override_settings(
        RESEND_TEST_SEND_ENABLED=True,
        RESEND_API_KEY="test-key",
        RESEND_FROM_EMAIL="Yo-kai Mail <test@example.com>",
    )
    @patch("campaigns.services.ResendEmailService.send_test_email")
    @patch("campaigns.services.compile_mjml_to_html")
    def test_test_send_does_not_approve_a_newer_design(
        self,
        compile_mock,
        send_mock,
    ):
        from .models import CampaignDesignVersion

        self._authenticate()
        campaign = self._create_generated_campaign_with_design()

        compile_mock.return_value = {
            "html": "<html><body>Old design</body></html>",
            "compiler_errors": [],
        }

        def send_side_effect(**kwargs):
            newer = CampaignDesignVersion.objects.create(
                campaign=campaign,
                version=2,
                source="user_edit",
                email_design=sample_persisted_email_design(
                    subject="Newer design"
                ),
                created_by=self.owner,
            )
            type(campaign).objects.filter(pk=campaign.pk).update(
                active_design_id=newer.id
            )
            return {
                "email_id": "email-old-design",
                "provider": "resend",
                "to": "owner@example.com",
                "from": "Yo-kai Mail <test@example.com>",
                "idempotency_key": "old-design-test",
                "inline_assets": [],
                "inline_asset_count": 0,
                "inline_asset_bytes": 0,
            }

        send_mock.side_effect = send_side_effect

        response = self.client.post(
            reverse(
                "campaign-send-test",
                kwargs={"campaign_id": campaign.id},
            ),
            {"to": "owner@example.com"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "generated")
        self.assertEqual(campaign.active_design.version, 2)
        self.assertIsNone(campaign.test_sent_at)

    @override_settings(
        RESEND_TEST_SEND_ENABLED=True,
        RESEND_API_KEY="test-key",
        RESEND_FROM_EMAIL="Yo-kai Mail <test@example.com>",
    )
    @patch("campaigns.services.ResendEmailService.send_test_email")
    @patch("campaigns.services.compile_mjml_to_html")
    def test_generated_to_test_send_to_ready_campaign_flow(
        self,
        compile_mock,
        send_mock,
    ):
        self._authenticate()
        campaign = self._create_generated_campaign_with_design()

        compile_mock.return_value = {
            "html": "<html><body>Campaign email</body></html>",
            "compiler_errors": [],
        }
        send_mock.return_value = {
            "email_id": "email-test-123",
            "provider": "resend",
            "to": "owner@example.com",
            "from": "Yo-kai Mail <test@example.com>",
            "idempotency_key": "test-key",
            "inline_assets": [],
            "inline_asset_count": 0,
            "inline_asset_bytes": 0,
        }

        send_response = self.client.post(
            reverse(
                "campaign-send-test",
                kwargs={"campaign_id": campaign.id},
            ),
            {"to": "owner@example.com"},
            format="json",
        )

        self.assertEqual(
            send_response.status_code,
            status.HTTP_200_OK,
        )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "test_sent")
        self.assertIsNotNone(campaign.reviewed_at)
        self.assertIsNotNone(campaign.test_sent_at)
        self.assertEqual(
            send_response.data["data"]["delivery"]["email_id"],
            "email-test-123",
        )

        ready_response = self.client.post(
            reverse(
                "campaign-transition",
                kwargs={"campaign_id": campaign.id},
            ),
            {"status": "ready"},
            format="json",
        )

        self.assertEqual(
            ready_response.status_code,
            status.HTTP_200_OK,
        )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "ready")
        self.assertIsNotNone(campaign.ready_at)
