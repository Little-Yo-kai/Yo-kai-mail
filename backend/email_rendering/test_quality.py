import os
from unittest import skipUnless

from django.test import SimpleTestCase

from .compiler import compile_mjml_to_html
from .renderer import render_email_to_mjml
from .tests import sample_assets, sample_brand_profile, sample_email_design


class EmailLayoutQualityTests(SimpleTestCase):
    def render(self, design):
        return render_email_to_mjml(
            brand_profile=sample_brand_profile(), email_design=design,
            asset_inventory=sample_assets(),
        )

    def test_grid_preserves_section_copy_and_cta_with_and_without_items(self):
        for items in [[], [{"title": "A product", "body": "Verified product copy"}]]:
            with self.subTest(items=items):
                design = sample_email_design()
                section = design["sections"][1]
                section["layout"] = "grid_2"
                section["items"] = items
                section["cta"] = {"label": "See the product", "url": "https://example.com/product"}
                mjml = self.render(design)["mjml"]
                self.assertIn("The Story", mjml)
                self.assertIn(section["body"], mjml)
                self.assertIn("See the product", mjml)
                self.assertEqual(mjml.count("A product"), 1 if items else 0)

    def test_split_preserves_item_copy_and_image(self):
        design = sample_email_design()
        section = design["sections"][1]
        section["layout"] = "split_image_left"
        section["asset_ids"] = ["og_image"]
        section["items"] = [{"title": "A useful benefit", "body": "Verified benefit copy"}]
        mjml = self.render(design)["mjml"]
        self.assertIn("A useful benefit", mjml)
        self.assertIn("Verified benefit copy", mjml)
        self.assertIn('src="https://example.com/product.jpg"', mjml)

    def test_replacing_an_inventory_image_updates_the_existing_design(self):
        design = sample_email_design()
        assets = sample_assets()
        before = self.render(design)["mjml"]
        assets[0]["url"] = "https://cdn.example.com/replacement.jpg"
        after = render_email_to_mjml(
            brand_profile=sample_brand_profile(), email_design=design,
            asset_inventory=assets,
        )["mjml"]
        self.assertIn('src="https://example.com/product.jpg"', before)
        self.assertIn('src="https://cdn.example.com/replacement.jpg"', after)
        self.assertNotIn('src="https://example.com/product.jpg"', after)

    def test_semantic_headings_and_merge_copy_remain_escaped(self):
        design = sample_email_design()
        design["sections"][0]["headline"] = "Hello {{ first_name }} <friend> & team"
        design["sections"][2]["cta"]["url"] = "https://example.com/?a=1&b=2"
        mjml = self.render(design)["mjml"]
        self.assertIn("<h1 ", mjml)
        self.assertIn("<h2 ", mjml)
        self.assertIn("Hello {{ first_name }} &lt;friend&gt; &amp; team", mjml)
        self.assertIn('href="https://example.com/?a=1&amp;b=2"', mjml)

    def test_stored_unsafe_cta_is_omitted_with_actionable_warnings(self):
        design = sample_email_design()
        design["sections"][2]["cta"]["url"] = "https://[broken"
        result = self.render(design)
        self.assertNotIn("<mj-button", result["mjml"])
        self.assertIn("missing-href", [warning["code"] for warning in result["warnings"]])
        self.assertIn("missing-footer", [warning["code"] for warning in result["warnings"]])

    @skipUnless(os.environ.get("EMAIL_RUNTIME_SMOKE") == "1", "Enable EMAIL_RUNTIME_SMOKE for the real MJML runtime")
    def test_real_compiler_preserves_grid_copy_headings_and_cta(self):
        design = sample_email_design()
        section = design["sections"][1]
        section["layout"] = "grid_2"
        section["items"] = [{"title": "A product", "body": "Verified product copy"}]
        compiled = compile_mjml_to_html(self.render(design)["mjml"])
        self.assertEqual(compiled["compiler_errors"], [])
        self.assertIn("<h1 ", compiled["html"])
        self.assertIn("<h2 ", compiled["html"])
        self.assertIn("<h3 ", compiled["html"])
        self.assertIn(section["body"], compiled["html"])
        self.assertIn('href="https://example.com/product"', compiled["html"])
