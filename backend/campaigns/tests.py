from django.contrib.auth import get_user_model
from django.urls import reverse
from unittest.mock import patch
from rest_framework import status
from rest_framework.test import APITestCase


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
