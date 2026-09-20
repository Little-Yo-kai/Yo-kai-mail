import json

from django.conf import settings
from google import genai
from pydantic import ValidationError

from brand_intelligence.schemas import BrandProfile
from reference_design.schemas import ReferenceDesignSpec

from ..builders import normalize_email_design
from ..prompts import EMAIL_DESIGN_COMPOSER_PROMPT
from ..schemas import AssetDescriptor, ContentPlan, EmailDesign, FactLedger
from .gemini import (
    GeminiGenerationNotConfiguredError,
)


class EmailDesignGenerationError(RuntimeError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.details = details


class GeminiEmailDesignComposer:
    def __init__(self, client=None):
        if client is not None:
            self.client = client
            return

        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise GeminiGenerationNotConfiguredError(
                "GEMINI_API_KEY is not configured."
            )

        self.client = genai.Client(api_key=api_key)

    def compose(
        self,
        *,
        brand_profile: dict,
        reference_design_spec: dict,
        content_plan: dict,
        asset_inventory: list[dict],
        fact_ledger: dict,
    ) -> dict:
        try:
            brand = BrandProfile.model_validate(brand_profile)
            reference = ReferenceDesignSpec.model_validate(
                reference_design_spec
            )
            plan = ContentPlan.model_validate(content_plan)
            assets = [
                AssetDescriptor.model_validate(item)
                for item in asset_inventory
            ]
            facts = FactLedger.model_validate(fact_ledger)
        except ValidationError as exc:
            raise EmailDesignGenerationError(
                "Invalid input contract for EmailDesign generation.",
                details=str(exc),
            ) from exc

        input_payload = {
            "brand_profile": brand.model_dump(mode="json"),
            "content_plan": plan.model_dump(mode="json"),
            "reference_design_spec": reference.model_dump(mode="json"),
            "asset_inventory": [
                asset.model_dump(mode="json")
                for asset in assets
            ],
            "fact_ledger": facts.model_dump(mode="json"),
        }

        prompt = (
            EMAIL_DESIGN_COMPOSER_PROMPT
            + "\n\nINPUT JSON:\n"
            + json.dumps(input_payload, ensure_ascii=False)
        )

        try:
            interaction = self.client.interactions.create(
                model=settings.GEMINI_GENERATION_MODEL,
                input=prompt,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": EmailDesign.model_json_schema(),
                },
            )

            output_text = getattr(interaction, "output_text", None)
            if not output_text:
                raise EmailDesignGenerationError(
                    "Gemini returned an empty EmailDesign."
                )

            design = EmailDesign.model_validate_json(output_text)
            design = normalize_email_design(
                design,
                asset_inventory=assets,
                fact_ledger=facts,
            )
        except EmailDesignGenerationError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise EmailDesignGenerationError(
                "Gemini returned an invalid EmailDesign.",
                details=str(exc),
            ) from exc
        except Exception as exc:
            raise EmailDesignGenerationError(
                "Gemini email design request failed.",
                details=str(exc),
            ) from exc

        return {
            "email_design": design.model_dump(mode="json"),
            "asset_inventory": [
                asset.model_dump(mode="json")
                for asset in assets
            ],
        }
