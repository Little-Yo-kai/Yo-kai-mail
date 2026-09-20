import base64

from django.conf import settings
from google import genai
from pydantic import ValidationError

from ..prompts import REFERENCE_DESIGN_PROMPT
from ..schemas import ReferenceDesignSpec


class GeminiNotConfiguredError(RuntimeError):
    pass


class ReferenceDesignAnalysisError(RuntimeError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.details = details


class GeminiReferenceDesignService:
    def __init__(self, client=None):
        if client is not None:
            self.client = client
            return

        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise GeminiNotConfiguredError("GEMINI_API_KEY is not configured.")

        self.client = genai.Client(api_key=api_key)

    def analyze(self, image_file) -> dict:
        image_file.seek(0)
        image_bytes = image_file.read()
        mime_type = image_file.content_type
        encoded_image = base64.b64encode(image_bytes).decode("utf-8")

        try:
            interaction = self.client.interactions.create(
                model=settings.GEMINI_MODEL,
                input=[
                    {
                        "type": "text",
                        "text": REFERENCE_DESIGN_PROMPT,
                    },
                    {
                        "type": "image",
                        "data": encoded_image,
                        "mime_type": mime_type,
                    },
                ],
                response_format=[
                    {
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": ReferenceDesignSpec.model_json_schema(),
                    }
                ],
            )

            output_text = getattr(interaction, "output_text", None)
            if not output_text:
                raise ReferenceDesignAnalysisError(
                    "Gemini returned an empty reference design analysis."
                )

            spec = ReferenceDesignSpec.model_validate_json(output_text)
        except ReferenceDesignAnalysisError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise ReferenceDesignAnalysisError(
                "Gemini returned an invalid ReferenceDesignSpec.",
                details=str(exc),
            ) from exc
        except Exception as exc:
            raise ReferenceDesignAnalysisError(
                "Gemini reference design analysis request failed.",
                details=str(exc),
            ) from exc

        return spec.model_dump(mode="json")
