import json

from django.conf import settings
from google import genai
from pydantic import ValidationError

from brand_intelligence.schemas import BrandProfile
from email_generation.schemas import AssetDescriptor, EmailDesign
from reference_design.schemas import ReferenceDesignSpec

from ..prompts import DESIGN_CRITIC_PROMPT
from ..schemas import DesignCritique


class DesignCriticNotConfiguredError(RuntimeError):
    pass


class DesignCritiqueError(RuntimeError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.details = details


class GeminiDesignCritic:
    def __init__(self, client=None):
        if client is not None:
            self.client = client
            return

        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise DesignCriticNotConfiguredError(
                "GEMINI_API_KEY is not configured."
            )

        self.client = genai.Client(api_key=api_key)

    def critique(
        self,
        *,
        screenshot_base64: str,
        screenshot_mime_type: str,
        brand_profile: dict,
        email_design: dict,
        reference_design_spec: dict,
        asset_inventory: list[dict],
        render_metadata: dict,
    ) -> dict:
        try:
            brand = BrandProfile.model_validate(brand_profile)
            design = EmailDesign.model_validate(email_design)
            reference = ReferenceDesignSpec.model_validate(
                reference_design_spec
            )
            assets = [
                AssetDescriptor.model_validate(item)
                for item in asset_inventory
            ]
        except ValidationError as exc:
            raise DesignCritiqueError(
                "Invalid input contract for visual design critique.",
                details=str(exc),
            ) from exc

        context = {
            "brand_profile": brand.model_dump(mode="json"),
            "email_design": design.model_dump(mode="json"),
            "reference_design_spec": reference.model_dump(mode="json"),
            "asset_inventory": [
                {
                    "asset_id": asset.asset_id,
                    "kind": asset.kind,
                    "source": asset.source,
                }
                for asset in assets
            ],
            "render_metadata": render_metadata,
        }

        text_prompt = (
            DESIGN_CRITIC_PROMPT
            + "\n\nSTRUCTURED CONTEXT JSON:\n"
            + json.dumps(context, ensure_ascii=False)
        )

        try:
            interaction = self.client.interactions.create(
                model=settings.GEMINI_CRITIC_MODEL,
                input=[
                    {
                        "type": "text",
                        "text": text_prompt,
                    },
                    {
                        "type": "image",
                        "data": screenshot_base64,
                        "mime_type": screenshot_mime_type,
                    },
                ],
                response_format=[
                    {
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": DesignCritique.model_json_schema(),
                    }
                ],
            )

            output_text = getattr(interaction, "output_text", None)
            if not output_text:
                raise DesignCritiqueError(
                    "Gemini returned an empty DesignCritique."
                )

            critique = DesignCritique.model_validate_json(output_text)
        except DesignCritiqueError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise DesignCritiqueError(
                "Gemini returned an invalid DesignCritique.",
                details=str(exc),
            ) from exc
        except Exception as exc:
            raise DesignCritiqueError(
                "Gemini visual design critique request failed.",
                details=str(exc),
            ) from exc

        return critique.model_dump(mode="json")
