"""Focused contrast regressions and repeatable, entirely offline visual inputs."""

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from django.test import SimpleTestCase

from email_generation.services.validation import validate_email_design_contract

from .renderer import _contrast_text, render_email_to_mjml


def contrast_fixtures():
    root = Path(__file__).resolve().parents[1]
    base = json.loads((root / "demo_flow" / "fixtures" / "workflow.json").read_text(encoding="utf-8"))
    cases = json.loads((Path(__file__).parent / "fixtures" / "contrast_cases.json").read_text(encoding="utf-8"))
    fixtures = []
    for case in cases:
        fixture = copy.deepcopy(base)
        fixture["name"] = case["name"]
        brand = fixture["brand_profile"]
        brand["visual"]["color_scheme"] = case["color_scheme"]
        brand["visual"]["colors"].update(case["colors"])
        fixture["asset_inventory"] = [
            asset for asset in fixture["asset_inventory"]
            if asset["asset_id"] in case["asset_ids"]
        ]
        design = fixture["email_design"]
        design["theme"]["button_color_role"] = "secondary"
        hero = design["sections"][0]
        hero["layout"] = case["hero_layout"]
        hero["asset_ids"] = case["asset_ids"][:1]
        hero["style"]["background_role"] = "secondary"
        if case["product_grid"]:
            # Reuse the same verified product/copy for its two existing image
            # views; these fixtures add no product facts or destinations.
            design["sections"].insert(1, {
                "id": "product-details", "order": 2, "type": "product_grid",
                "layout": "grid_2", "headline": "Product details", "body": None,
                "asset_ids": [], "cta": None, "style": copy.deepcopy(hero["style"]),
                "items": [{
                    "title": fixture["fact_ledger"]["product_name"],
                    "body": hero["body"], "asset_id": asset_id,
                } for asset_id in case["asset_ids"]],
            })
        for order, section in enumerate(design["sections"], 1):
            section["order"] = order
        fixtures.append(fixture)
    return fixtures


class ForegroundContrastTests(SimpleTestCase):
    def test_midtones_choose_black_instead_of_the_failing_white_or_near_black(self):
        # WCAG ratios: #777 white=4.47809, #111=4.21677, black=4.68950;
        # #00AA00 white=3.11116, black=6.74989; orange white=2.39353.
        for background in ("#777777", "#777", "#00AA00", "#0a0", "#FF8800"):
            with self.subTest(background=background):
                self.assertEqual(_contrast_text(background), "#000000")

    def test_dark_and_light_extremes_keep_readable_foregrounds(self):
        for background, expected in (
            ("#111111", "#FFFFFF"), ("#000", "#FFFFFF"),
            ("#FFFFFF", "#000000"), ("#fff", "#000000"),
        ):
            with self.subTest(background=background):
                self.assertEqual(_contrast_text(background), expected)

    def test_invalid_colors_keep_the_white_fallback(self):
        for background in ("", "#", "#ABCD", "#GGGGGG", "##FFFFFF", None):
            with self.subTest(background=background):
                self.assertEqual(_contrast_text(background), "#FFFFFF")

    def test_supported_layouts_use_corrected_panel_and_button_foregrounds(self):
        fixtures = contrast_fixtures()
        self.assertEqual([fixture["name"] for fixture in fixtures], [
            "product-rich", "single-image", "asset-poor", "dark",
        ])
        for fixture in fixtures:
            with self.subTest(fixture=fixture["name"]):
                validate_email_design_contract(
                    fixture["email_design"], asset_inventory=fixture["asset_inventory"],
                    fact_ledger=fixture["fact_ledger"],
                )
                rendered = render_email_to_mjml(**{
                    key: fixture[key]
                    for key in ("brand_profile", "email_design", "asset_inventory")
                })
                root = ET.fromstring(rendered["mjml"])
                button = root.find(".//mj-button")
                self.assertIsNotNone(button)
                self.assertEqual(button.attrib["color"], "#000000")
                self.assertEqual(button.attrib["href"], fixture["fact_ledger"]["authoritative_destination_url"])
                panel = next(section for section in root.findall(".//mj-section")
                             if section.attrib.get("background-color") == fixture["brand_profile"]["visual"]["colors"]["secondary"])
                self.assertTrue(panel.findall(".//mj-text"))
                self.assertTrue(all(text.attrib["color"] == "#000000" for text in panel.findall(".//mj-text")))
