import hashlib
import logging
import time

from django.conf import settings

from brand_intelligence.prompts import BRAND_ANALYSIS_PROMPT
from brand_intelligence.schemas import BrandAnalysis
from brand_intelligence.services.gemini import GeminiBrandService
from core.generation_budget import report_stage, with_generation_budget
from core.preparation_cache import fingerprint
from email_generation.prompts import CONTENT_STRATEGIST_PROMPT
from email_generation.schemas import ContentPlan
from email_generation.services.composer import GeminiEmailDesignComposer
from email_generation.services.gemini import GeminiCampaignStrategist
from email_rendering.compiler import compile_mjml_to_html
from email_rendering.renderer import render_email_to_mjml
from reference_design.prompts import REFERENCE_DESIGN_PROMPT
from reference_design.schemas import ReferenceDesignSpec
from reference_design.services.gemini import GeminiReferenceDesignService
from reference_library.selector import select_reference
from website_intelligence.normalizers import build_website_snapshot
from website_intelligence.services.firecrawl import FirecrawlService

from .preparation import prepare, start_reference_preparation, wait_for_reference
from .preview import build_preview_html

logger = logging.getLogger(__name__)
_WEBSITE_FORMATS = tuple(FirecrawlService.FORMATS)


def _ai_identity(model, prompt, schema):
    return {
        "model": model,
        "fallback": settings.GEMINI_FALLBACK_MODEL,
        "additional_fallbacks": settings.GEMINI_ADDITIONAL_FALLBACK_MODELS,
        "credential": fingerprint(settings.GEMINI_API_KEY),
        "prompt": prompt,
        "schema": schema.model_json_schema(),
    }


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
    snapshot: dict | None = None,
    additional_instructions: str = "",
) -> dict:
    identity = brand_profile.get("identity") or {}
    brand_name = identity.get("name") or "this brand"
    product = (snapshot or {}).get("product")

    instructions = additional_instructions.strip()
    if not instructions:
        instructions = (
            "Create a focused product-discovery email using the supplied product "
            "evidence and real product imagery. Do not imply a new launch or promotion."
            if product
            else "Create a polished introductory marketing email using only "
            "verified brand information and available website assets."
        )

    return {
        "schema_version": "1.0",
        "campaign_type": "announcement" if product else "newsletter",
        "goal": "product_discovery" if product else "brand_awareness",
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
        "product": product,
        "destination_url": url,
        "tone_override": None,
        "additional_instructions": instructions,
    }


@with_generation_budget
def generate_phase1_demo(
    *,
    url: str,
    reference_image=None,
    additional_instructions: str = "",
    refresh_website: bool = False,
) -> dict:
    started = time.monotonic()
    timings = []
    stage = "website_import"

    try:

        def analyze_reference(image):
            image.seek(0)
            image_hash = hashlib.sha256(image.read()).hexdigest()
            image.seek(0)
            return prepare(
                "reference_selection",
                {
                    "image": image_hash,
                    "mime_type": image.content_type,
                    "ai": _ai_identity(
                        settings.GEMINI_REFERENCE_MODEL,
                        REFERENCE_DESIGN_PROMPT,
                        ReferenceDesignSpec,
                    ),
                },
                lambda: GeminiReferenceDesignService().analyze(image),
                timeout=settings.GENERATION_ANALYSIS_CACHE_SECONDS,
            )

        # The reference image is independent of the website and brand. Start
        # it now, then join at its normal progress stage without extra AI calls.
        reference_task = (
            start_reference_preparation(reference_image, analyze_reference)
            if reference_image is not None
            else None
        )

        report_stage(stage)
        website_max_age_ms = max(0, settings.GENERATION_WEBSITE_CACHE_SECONDS) * 1000
        snapshot, timing = prepare(
            stage,
            {
                "url": url,
                "normalizer_version": 4,
                "provider_max_age_ms": website_max_age_ms,
                "formats": _WEBSITE_FORMATS,
                "credential": fingerprint(settings.FIRECRAWL_API_KEY),
            },
            lambda: build_website_snapshot(
                url,
                FirecrawlService().scrape(
                    url,
                    max_age_ms=0 if refresh_website else website_max_age_ms,
                ),
            ),
            timeout=settings.GENERATION_WEBSITE_CACHE_SECONDS,
            refresh=refresh_website,
        )
        timings.append(timing)

        stage = "brand_analysis"
        report_stage(stage)
        brand_profile, timing = prepare(
            stage,
            {
                "snapshot": snapshot,
                "builder_version": 1,
                "ai": _ai_identity(
                    settings.GEMINI_MODEL, BRAND_ANALYSIS_PROMPT, BrandAnalysis
                ),
            },
            lambda: GeminiBrandService().analyze(snapshot),
            timeout=settings.GENERATION_ANALYSIS_CACHE_SECONDS,
            refresh=refresh_website,
        )
        timings.append(timing)

        campaign_brief = _default_campaign_brief(
            url=url,
            brand_profile=brand_profile,
            snapshot=snapshot,
            additional_instructions=additional_instructions,
        )

        stage = "reference_selection"
        report_stage(stage)
        if reference_image is not None:
            reference_design_spec, timing = (
                wait_for_reference(reference_task)
                if reference_task is not None
                else analyze_reference(reference_image)
            )
            timings.append(timing)
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
            reference_design_spec = selected_reference["reference_design_spec"]
            reference = {
                "source": "internal_library",
                "reference_id": selected_reference["reference_id"],
                "name": selected_reference["name"],
                "recipe_family": selected_reference["recipe_family"],
                "selection_reasons": selected_reference["selection_reasons"],
                "reference_design_spec": reference_design_spec,
            }

        stage = "content_plan"
        report_stage(stage)
        plan_result, timing = prepare(
            stage,
            {
                "brand_profile": brand_profile,
                "campaign_brief": campaign_brief,
                "reference_design_spec": reference_design_spec,
                "builder_version": 2,
                "compact_context": settings.GEMINI_COMPACT_CONTEXT_ENABLED,
                "ai": _ai_identity(
                    settings.GEMINI_GENERATION_MODEL,
                    CONTENT_STRATEGIST_PROMPT,
                    ContentPlan,
                ),
            },
            lambda: GeminiCampaignStrategist().plan(
                brand_profile=brand_profile,
                campaign_brief=campaign_brief,
                reference_design_spec=reference_design_spec,
            ),
            timeout=settings.GENERATION_PLAN_CACHE_SECONDS,
            refresh=refresh_website,
        )
        timings.append(timing)

        stage = "email_design"
        report_stage(stage)
        stage_started = time.monotonic()
        design_result = GeminiEmailDesignComposer().compose(
            brand_profile=brand_profile,
            reference_design_spec=reference_design_spec,
            content_plan=plan_result["content_plan"],
            asset_inventory=plan_result["asset_inventory"],
            fact_ledger=plan_result["fact_ledger"],
        )
        timings.append(
            {
                "stage": stage,
                "duration_seconds": round(time.monotonic() - stage_started, 3),
            }
        )

        stage = "render"
        report_stage(stage)
        stage_started = time.monotonic()
        render_result = render_email_to_mjml(
            brand_profile=brand_profile,
            email_design=design_result["email_design"],
            asset_inventory=design_result["asset_inventory"],
        )
        compile_result = compile_mjml_to_html(render_result["mjml"])
        timings.append(
            {
                "stage": stage,
                "duration_seconds": round(time.monotonic() - stage_started, 3),
            }
        )

        # Preview embedding is optional. A cache failure must not discard
        # the valid HTML that has already been generated and compiled.
        stage = "preview_assets"
        stage_started = time.monotonic()
        try:
            report_stage(stage)
            preview_html, preview_asset_diagnostics, cached_assets = build_preview_html(
                html_document=compile_result["html"],
                asset_inventory=design_result["asset_inventory"],
            )
        except Exception:
            logger.warning(
                "Preview embedding failed; returning compiled email", exc_info=True
            )
            preview_html = compile_result["html"]
            preview_asset_diagnostics = [
                {
                    "status": "unavailable",
                    "reason": "Preview images could not be cached. Original image URLs are retained.",
                }
            ]
            cached_assets = []
        timings.append(
            {
                "stage": stage,
                "duration_seconds": round(time.monotonic() - stage_started, 3),
            }
        )

        return {
            "performance": {
                "total_seconds": round(time.monotonic() - started, 3),
                "reused_stages": [
                    item["stage"]
                    for item in timings
                    if item.get("cache") in {"hit", "shared"}
                ],
                "stages": timings,
            },
            "mode": (
                "uploaded_reference"
                if reference_image is not None
                else "automatic_reference"
            ),
            "brand_profile": brand_profile,
            "campaign_brief": campaign_brief,
            "reference": reference,
            "content_plan": plan_result["content_plan"],
            "fact_ledger": plan_result["fact_ledger"],
            "email_design": design_result["email_design"],
            "generation_recovery_actions": design_result.get(
                "recovery_actions",
                [],
            ),
            "asset_inventory": design_result["asset_inventory"],
            "render": {
                "html": compile_result["html"],
                "text": compile_result.get("text", ""),
                "warnings": render_result.get("warnings", []),
                "preview_html": preview_html,
                "preview_asset_diagnostics": preview_asset_diagnostics,
                "cached_assets": cached_assets,
                "delivery_ready": all(
                    item["status"] == "embedded" for item in preview_asset_diagnostics
                ),
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
