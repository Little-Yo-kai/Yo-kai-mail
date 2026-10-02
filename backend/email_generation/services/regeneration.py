import copy
import json

from django.conf import settings
from google import genai
from pydantic import ValidationError

from core.ai_fallback import call_with_model_fallback
from brand_intelligence.schemas import BrandProfile
from reference_design.schemas import ReferenceDesignSpec

from ..builders import normalize_email_design
from ..schemas import AssetDescriptor, ContentPlan, EmailDesign, FactLedger
from .composer import EmailDesignGenerationError
from .validation import EmailDesignContractError, validate_email_design_contract


class GeminiSectionRegenerator:
    """Regenerate one EmailSection while application code owns invariants."""

    def __init__(self, client=None):
        if client is not None:
            self.client = client
            return
        if not settings.GEMINI_API_KEY:
            raise EmailDesignGenerationError(
                "GEMINI_API_KEY is not configured.",
                reason="Generation request failed",
            )
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def regenerate(
        self,
        *,
        current_design: dict,
        section_id: str,
        brand_profile: dict,
        reference_design_spec: dict,
        content_plan: dict,
        asset_inventory: list[dict],
        fact_ledger: dict,
    ) -> dict:
        try:
            design = validate_email_design_contract(
                current_design,
                asset_inventory=asset_inventory,
                fact_ledger=fact_ledger,
            )
            brand = BrandProfile.model_validate(brand_profile)
            reference = ReferenceDesignSpec.model_validate(reference_design_spec)
            plan = ContentPlan.model_validate(content_plan)
            assets = [AssetDescriptor.model_validate(item) for item in asset_inventory]
            facts = FactLedger.model_validate(fact_ledger)
        except (ValidationError, EmailDesignContractError) as exc:
            raise EmailDesignGenerationError(
                "Current EmailDesign cannot be regenerated safely.",
                details=str(exc),
                reason="Invalid current EmailDesign",
            ) from exc

        target = next((s for s in design.sections if s.id == section_id), None)
        if target is None:
            raise EmailDesignGenerationError(
                f"Section {section_id!r} was not found.",
                reason="Section not found",
            )

        prompt = (
            "Regenerate exactly ONE EmailSection for Yo-kai Mail. "
            "Return only a single JSON EmailSection object. Never return "
            "HTML, MJML, CSS, or a full EmailDesign. Preserve the section id, "
            "type, layout, style, order, factual boundaries, and approved "
            "asset IDs. Do not invent CTA URLs; the application owns CTA "
            "destinations. Do not modify any other section or top-level field.\n\n"
            "BRAND PROFILE:\n"
            + json.dumps(brand.model_dump(mode="json"), ensure_ascii=False)
            + "\n\nREFERENCE DESIGN:\n"
            + json.dumps(reference.model_dump(mode="json"), ensure_ascii=False)
            + "\n\nCONTENT PLAN:\n"
            + json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)
            + "\n\nFACT LEDGER:\n"
            + json.dumps(facts.model_dump(mode="json"), ensure_ascii=False)
            + "\n\nAPPROVED ASSETS:\n"
            + json.dumps([a.model_dump(mode="json") for a in assets], ensure_ascii=False)
            + "\n\nCURRENT SECTION:\n"
            + json.dumps(target.model_dump(mode="json"), ensure_ascii=False)
        )

        try:
            interaction = call_with_model_fallback(
                self.client.interactions.create,
                primary_model=settings.GEMINI_GENERATION_MODEL,
                fallback_model=settings.GEMINI_FALLBACK_MODEL,
                input=prompt,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": EmailDesign.model_json_schema()[
                        "$defs"
                    ]["EmailSection"],
                },
            )
            output_text = getattr(interaction, "output_text", None)
            if not output_text:
                raise ValueError("Empty structured section output.")
            payload = json.loads(output_text)
            regenerated = design.sections[0].__class__.model_validate(payload)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise EmailDesignGenerationError(
                "Regenerated section did not satisfy the structured contract.",
                details=str(exc),
                reason="Invalid structured output",
            ) from exc
        except Exception as exc:
            raise EmailDesignGenerationError(
                "Section regeneration request failed.",
                details=str(exc),
                reason="Generation request failed",
            ) from exc

        if regenerated.id != target.id or regenerated.type != target.type:
            raise EmailDesignGenerationError(
                "Regenerated section changed application-owned identity.",
                reason="Invalid regenerated section",
            )

        # Preserve application-owned structural fields even if the model
        # attempted to alter them.
        regenerated.order = target.order
        regenerated.layout = target.layout
        regenerated.style = copy.deepcopy(target.style)

        authoritative_url = facts.authoritative_destination_url
        if regenerated.cta is not None:
            regenerated.cta.url = authoritative_url
        for item in regenerated.items:
            if item.cta is not None:
                item.cta.url = authoritative_url

        merged = design.model_copy(deep=True)
        for index, section in enumerate(merged.sections):
            if section.id == section_id:
                merged.sections[index] = regenerated
                break

        try:
            merged = normalize_email_design(
                merged,
                asset_inventory=assets,
                fact_ledger=facts,
            )
            validated = validate_email_design_contract(
                merged,
                asset_inventory=assets,
                fact_ledger=facts,
            )
        except (ValidationError, EmailDesignContractError) as exc:
            raise EmailDesignGenerationError(
                "Regenerated EmailDesign failed application validation.",
                details=str(exc),
                reason="Invalid regenerated section",
            ) from exc

        return {"email_design": validated.model_dump(mode="json")}
