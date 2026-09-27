from django.urls import reverse
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
