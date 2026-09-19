import json

from django.conf import settings
from google import genai
from pydantic import ValidationError

from ..builders import build_brand_profile
from ..prompts import BRAND_ANALYSIS_PROMPT
from ..schemas import BrandAnalysis


class GeminiNotConfiguredError(RuntimeError):
    pass


class BrandAnalysisError(RuntimeError):
    pass


def _snapshot_for_model(snapshot: dict) -> dict:
    source = snapshot.get("source") or {}
    content = snapshot.get("content") or {}
    visual = snapshot.get("visual") or {}
    assets = snapshot.get("assets") or {}
    detected_branding = snapshot.get("detected_branding") or {}

    markdown = content.get("markdown") or ""

    return {
        "source": source,
        "content": {"markdown": markdown[:12000]},
        "visual": {"screenshot_url": visual.get("screenshot")},
        "assets": {
            "logo_candidate": assets.get("logo_candidate"),
            "favicon": assets.get("favicon"),
            "og_image": assets.get("og_image"),
            "images": (assets.get("images") or [])[:8],
        },
        "detected_branding": detected_branding,
    }


class GeminiBrandService:
    def __init__(self, client=None):
        if client is not None:
            self.client = client
            return

        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise GeminiNotConfiguredError("GEMINI_API_KEY is not configured.")

        self.client = genai.Client(api_key=api_key)

    def analyze(self, snapshot: dict) -> dict:
        evidence = _snapshot_for_model(snapshot)
        prompt = (
            f"{BRAND_ANALYSIS_PROMPT}\n\n"
            "WEBSITE_SNAPSHOT:\n"
            f"{json.dumps(evidence, ensure_ascii=False)}"
        )

        try:
            interaction = self.client.interactions.create(
                model=settings.GEMINI_MODEL,
                input=prompt,
                response_format=[
                    {
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": BrandAnalysis.model_json_schema(),
                    }
                ],
            )
            output_text = getattr(interaction, "output_text", None)
            if not output_text:
                raise BrandAnalysisError("Gemini returned an empty analysis.")

            analysis = BrandAnalysis.model_validate_json(output_text)
        except BrandAnalysisError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise BrandAnalysisError(
                "Gemini returned an invalid BrandProfile response."
            ) from exc
        except Exception as exc:
            raise BrandAnalysisError(
                "Gemini brand analysis request failed."
            ) from exc

        return build_brand_profile(snapshot, analysis).model_dump(mode="json")
