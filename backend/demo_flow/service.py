from email_generation.services.composer import GeminiEmailDesignComposer
from email_generation.services.gemini import GeminiCampaignStrategist
from email_rendering.compiler import compile_mjml_to_html
from email_rendering.renderer import render_email_to_mjml
from reference_design.services.gemini import GeminiReferenceDesignService
from reference_library.selector import select_reference
from brand_intelligence.services.gemini import GeminiBrandService
from website_intelligence.normalizers import build_website_snapshot
from website_intelligence.services.firecrawl import FirecrawlService


class DemoGenerationError(RuntimeError):
    def __init__(
        self,
        stage: str,
        message: str,
        details: str | None = None,
    ):
        super().__init__(message)
        self.stage = stage
        self.details = details


def _default_campaign_brief(
    *,
    url: str,
    brand_profile: dict,
    additional_instructions: str = "",
) -> dict:
    identity = brand_profile.get("identity") or {}
    brand_name = identity.get("name") or "this brand"

    instructions = additional_instructions.strip()
    if not instructions:
        instructions = (
            "Create a polished introductory marketing email using only "
            "verified brand information and available website assets."
        )

    return {
        "schema_version": "1.0",
        "campaign_type": "newsletter",
        "goal": "brand_awareness",
        "audience": {
            "description": (
                f"Prospective customers and people interested in {brand_name}."
            ),
        },
        "offer": {
            "type": "none",
            "value": None,
            "code": None,
            "details": None,
        },
        "product": None,
        "destination_url": url,
        "tone_override": None,
        "additional_instructions": instructions,
    }


def generate_phase1_demo(
    *,
    url: str,
    reference_image=None,
    additional_instructions: str = "",
) -> dict:
    stage = "website_import"

    try:
        raw_data = FirecrawlService().scrape(url)
        snapshot = build_website_snapshot(url, raw_data)

        stage = "brand_analysis"
        brand_profile = GeminiBrandService().analyze(snapshot)

        campaign_brief = _default_campaign_brief(
            url=url,
            brand_profile=brand_profile,
            additional_instructions=additional_instructions,
        )

        stage = "reference_selection"
        if reference_image is not None:
            reference_design_spec = GeminiReferenceDesignService().analyze(
                reference_image
            )
            reference = {
                "source": "uploaded_reference",
                "name": "Uploaded reference image",
                "reference_design_spec": reference_design_spec,
            }
        else:
            selected_reference = select_reference(
                brand_profile,
                campaign_brief,
            )
            reference_design_spec = selected_reference[
                "reference_design_spec"
            ]
            reference = {
                "source": "internal_library",
                "reference_id": selected_reference["reference_id"],
                "name": selected_reference["name"],
                "recipe_family": selected_reference["recipe_family"],
                "selection_reasons": selected_reference[
                    "selection_reasons"
                ],
                "reference_design_spec": reference_design_spec,
            }

        stage = "content_plan"
        plan_result = GeminiCampaignStrategist().plan(
            brand_profile=brand_profile,
            campaign_brief=campaign_brief,
            reference_design_spec=reference_design_spec,
        )

        stage = "email_design"
        design_result = GeminiEmailDesignComposer().compose(
            brand_profile=brand_profile,
            reference_design_spec=reference_design_spec,
            content_plan=plan_result["content_plan"],
            asset_inventory=plan_result["asset_inventory"],
            fact_ledger=plan_result["fact_ledger"],
        )

        stage = "render"
        render_result = render_email_to_mjml(
            brand_profile=brand_profile,
            email_design=design_result["email_design"],
            asset_inventory=design_result["asset_inventory"],
        )
        compile_result = compile_mjml_to_html(
            render_result["mjml"]
        )

        return {
            "mode": (
                "uploaded_reference"
                if reference_image is not None
                else "automatic_reference"
            ),
            "brand_profile": brand_profile,
            "campaign_brief": campaign_brief,
            "reference": reference,
            "content_plan": plan_result["content_plan"],
            "email_design": design_result["email_design"],
            "asset_inventory": design_result["asset_inventory"],
            "render": {
                "html": compile_result["html"],
                "mjml": render_result["mjml"],
                "compiler_errors": compile_result["compiler_errors"],
                "resolved_theme": render_result["resolved_theme"],
                "rendered_sections": render_result["rendered_sections"],
            },
        }
    except DemoGenerationError:
        raise
    except Exception as exc:
        raise DemoGenerationError(
            stage=stage,
            message=f"Phase 1 demo failed during {stage}.",
            details=getattr(exc, "details", None) or str(exc),
        ) from exc
