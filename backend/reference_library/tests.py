from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .selector import select_reference


def brand_profile(
    *,
    industry="Luxury Fashion & Leather Goods",
    tones=None,
    images=None,
):
    tones = tones or [
        "luxurious",
        "sophisticated",
        "refined",
        "exclusive",
    ]
    images = images or ["https://example.com/hero.jpg"]

    return {
        "schema_version": "1.0",
        "identity": {
            "name": "Example Brand",
            "industry": industry,
        },
        "communication": {
            "tone": tones,
        },
        "assets": {
            "hero_candidates": images,
            "og_image": images[0] if images else None,
        },
    }


def campaign_brief(
    *,
    campaign_type="product_launch",
    goal="drive_sales",
    offer_type="none",
    product=True,
):
    return {
        "schema_version": "1.0",
        "campaign_type": campaign_type,
        "goal": goal,
        "audience": {
            "description": "Existing customers",
        },
        "offer": {
            "type": offer_type,
            "value": "20%" if offer_type != "none" else None,
            "code": None,
            "details": None,
        },
        "product": (
            {
                "name": "Example Product",
                "url": "https://example.com/product",
                "description": "Example product.",
            }
            if product
            else None
        ),
    }


class ReferenceSelectorTests(APITestCase):
    def test_luxury_product_launch_selects_luxury_editorial(self):
        result = select_reference(
            brand_profile(),
            campaign_brief(goal="product_discovery"),
        )

        self.assertEqual(
            result["reference_id"],
            "luxury_editorial_launch_v1",
        )
        self.assertEqual(result["source"], "internal_library")
        self.assertIn("reference_design_spec", result)

    def test_electronics_launch_selects_feature_led_direction(self):
        result = select_reference(
            brand_profile(
                industry="Consumer Electronics & Audio",
                tones=["bold", "technical", "modern", "confident"],
                images=[
                    "https://example.com/hero.jpg",
                    "https://example.com/product.jpg",
                    "https://example.com/lifestyle.jpg",
                ],
            ),
            campaign_brief(goal="product_discovery"),
        )

        self.assertEqual(
            result["reference_id"],
            "feature_product_launch_v1",
        )
        self.assertTrue(result["asset_fit"]["sufficient_images"])

    def test_discount_promotion_selects_promotional_direction(self):
        result = select_reference(
            brand_profile(
                industry="Beauty Retail",
                tones=["bold", "playful", "energetic"],
                images=[
                    "https://example.com/one.jpg",
                    "https://example.com/two.jpg",
                ],
            ),
            campaign_brief(
                campaign_type="promotion",
                goal="drive_sales",
                offer_type="percentage_discount",
                product=False,
            ),
        )

        self.assertEqual(result["reference_id"], "bold_promotion_v1")
        self.assertTrue(
            any(
                "promotional offer" in reason
                for reason in result["selection_reasons"]
            )
        )


class ReferenceLibraryApiTests(APITestCase):
    def test_list_endpoint_returns_curated_catalog(self):
        response = self.client.get(reverse("reference-library-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertGreaterEqual(len(response.data["data"]), 8)

    def test_select_endpoint_returns_reference_design_spec(self):
        response = self.client.post(
            reverse("reference-library-select"),
            {
                "brand_profile": brand_profile(),
                "campaign_brief": campaign_brief(
                    goal="product_discovery",
                ),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["reference_id"],
            "luxury_editorial_launch_v1",
        )
        self.assertEqual(
            response.data["data"]["reference_design_spec"][
                "schema_version"
            ],
            "1.0",
        )
