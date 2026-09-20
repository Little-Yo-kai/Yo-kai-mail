import json

from django.conf import settings
from google import genai
from pydantic import ValidationError

from ..builders import build_asset_inventory, normalize_content_plan
from ..prompts import CONTENT_STRATEGIST_PROMPT
from ..schemas import ContentPlan


class GeminiGenerationNotConfiguredError(RuntimeError):
    pass


class ContentPlanGenerationError(RuntimeError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.details = details


class GeminiCampaignStrategist:
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

    def plan(
        self,
        *,
        brand_profile: dict,
        campaign_brief: dict,
        reference_design_spec: dict,
        available_assets: list[dict] | None = None,
    ) -> dict:
        asset_inventory = build_asset_inventory(
            brand_profile,
            available_assets,
        )

        input_payload = {
            "brand_profile": brand_profile,
            "campaign_brief": campaign_brief,
            "reference_design_spec": reference_design_spec,
            "asset_inventory": [
                asset.model_dump(mode="json")
                for asset in asset_inventory
            ],
        }

        prompt = (
            CONTENT_STRATEGIST_PROMPT
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
                    "schema": ContentPlan.model_json_schema(),
                },
            )

            output_text = getattr(interaction, "output_text", None)
            if not output_text:
                raise ContentPlanGenerationError(
                    "Gemini returned an empty ContentPlan."
                )

            plan = ContentPlan.model_validate_json(output_text)
            plan = normalize_content_plan(
                plan,
                campaign_brief=campaign_brief,
                asset_inventory=asset_inventory,
            )
        except ContentPlanGenerationError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise ContentPlanGenerationError(
                "Gemini returned an invalid ContentPlan.",
                details=str(exc),
            ) from exc
        except Exception as exc:
            raise ContentPlanGenerationError(
                "Gemini campaign strategy request failed.",
                details=str(exc),
            ) from exc

        return {
            "content_plan": plan.model_dump(mode="json"),
            "asset_inventory": [
                asset.model_dump(mode="json")
                for asset in asset_inventory
            ],
        }
