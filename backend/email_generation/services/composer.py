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

    def _request_design(self, prompt: str) -> str:
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

        return output_text

    @staticmethod
    def _repair_prompt(
        *,
        original_prompt: str,
        invalid_output: str,
        validation_error: Exception,
    ) -> str:
        if isinstance(validation_error, ValidationError):
            error_payload = validation_error.errors(include_url=False)
        else:
            error_payload = [
                {
                    "type": type(validation_error).__name__,
                    "message": str(validation_error),
                }
            ]

        return (
            original_prompt
            + "\n\nREPAIR TASK:\n"
            + "Your previous EmailDesign did not satisfy the required "
            + "application contract. Repair the EmailDesign only. Preserve "
            + "the approved campaign strategy, factual boundaries, asset "
            + "constraints, section intent, and recipient-facing meaning. "
            + "Do not remove required content merely to satisfy validation. "
            + "Return a complete replacement EmailDesign, not a patch.\n\n"
            + "PREVIOUS INVALID EMAILDESIGN:\n"
            + invalid_output
            + "\n\nAPPLICATION VALIDATION ERRORS:\n"
            + json.dumps(
                error_payload,
                ensure_ascii=False,
                default=str,
            )
        )

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
            output_text = self._request_design(prompt)

            try:
                design = EmailDesign.model_validate_json(output_text)
            except (ValidationError, ValueError, TypeError) as first_error:
                repair_prompt = self._repair_prompt(
                    original_prompt=prompt,
                    invalid_output=output_text,
                    validation_error=first_error,
                )
                repaired_output = self._request_design(repair_prompt)

                try:
                    design = EmailDesign.model_validate_json(
                        repaired_output
                    )
                except (
                    ValidationError,
                    ValueError,
                    TypeError,
                ) as repair_error:
                    raise EmailDesignGenerationError(
                        (
                            "Gemini returned an invalid EmailDesign after "
                            "one repair attempt."
                        ),
                        details=str(repair_error),
                    ) from repair_error

            design = normalize_email_design(
                design,
                asset_inventory=assets,
                fact_ledger=facts,
            )
        except EmailDesignGenerationError:
            raise
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
