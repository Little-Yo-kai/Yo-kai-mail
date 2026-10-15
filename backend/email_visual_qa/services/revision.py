import json

from django.conf import settings
from google import genai
from pydantic import ValidationError

from brand_intelligence.schemas import BrandProfile
from core.ai_fallback import call_with_model_fallback
from email_generation.builders import (
    normalize_email_design,
    repair_email_design_payload,
)
from email_generation.schemas import (
    AssetDescriptor,
    ContentPlan,
    EmailDesign,
    FactLedger,
)
from email_rendering.compiler import (
    MJMLCompilerError,
    compile_mjml_to_html,
)
from email_rendering.renderer import (
    EmailRenderInputError,
    render_email_to_mjml,
)
from email_rendering.screenshot import (
    EmailScreenshotError,
    capture_email_screenshot,
)
from reference_design.schemas import ReferenceDesignSpec

from ..prompts import EMAIL_DESIGN_REVISION_PROMPT
from ..schemas import DesignCritique
from .gemini import (
    DesignCriticNotConfiguredError,
    DesignCritiqueError,
    GeminiDesignCritic,
)


class EmailDesignRevisionError(RuntimeError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.details = details


class GeminiEmailDesignReviser:
    def __init__(self, client=None, critic=None):
        if client is not None:
            self.client = client
        else:
            api_key = settings.GEMINI_API_KEY
            if not api_key:
                raise DesignCriticNotConfiguredError(
                    "GEMINI_API_KEY is not configured."
                )
            self.client = genai.Client(api_key=api_key)

        self.critic = critic or GeminiDesignCritic(client=self.client)

    @staticmethod
    def _bounded_max_attempts(
        max_revision_attempts: int | None,
    ) -> int:
        configured_default = getattr(
            settings,
            "EMAIL_DESIGN_REVISION_MAX_ATTEMPTS",
            1,
        )
        candidate = (
            max_revision_attempts
            if isinstance(max_revision_attempts, int)
            else configured_default
        )
        return max(1, min(2, int(candidate)))

    def _request_revised_design(self, prompt: str) -> str:
        interaction = call_with_model_fallback(
            self.client.interactions.create,
            primary_model=getattr(
                settings,
                "GEMINI_REVISION_MODEL",
                settings.GEMINI_GENERATION_MODEL,
            ),
            fallback_model=settings.GEMINI_FALLBACK_MODEL,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": EmailDesign.model_json_schema(),
            },
        )

        output_text = getattr(interaction, "output_text", None)
        if not output_text:
            raise EmailDesignRevisionError(
                "Gemini returned an empty revised EmailDesign."
            )
        return output_text

    @staticmethod
    def _validate_and_normalize_revised_design(
        output_text: str,
        *,
        content_plan: ContentPlan,
        fact_ledger: FactLedger,
        assets: list[AssetDescriptor],
    ) -> tuple[EmailDesign, list[str]]:
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError:
            payload = EmailDesign.model_validate_json(
                output_text
            ).model_dump(mode="json")

        if not isinstance(payload, dict):
            payload = EmailDesign.model_validate(payload).model_dump(
                mode="json"
            )

        repaired_payload, recovery_actions = repair_email_design_payload(
            payload,
            content_plan=content_plan,
            fact_ledger=fact_ledger,
        )
        design = EmailDesign.model_validate(repaired_payload)
        normalized = normalize_email_design(
            design,
            asset_inventory=assets,
            fact_ledger=fact_ledger,
        )
        return normalized, recovery_actions

    def _build_revision_prompt(
        self,
        *,
        brand: BrandProfile,
        reference: ReferenceDesignSpec,
        plan: ContentPlan,
        facts: FactLedger,
        assets: list[AssetDescriptor],
        email_design: EmailDesign,
        design_critique: DesignCritique,
    ) -> str:
        payload = {
            "brand_profile": brand.model_dump(mode="json"),
            "reference_design_spec": reference.model_dump(mode="json"),
            "content_plan": plan.model_dump(mode="json"),
            "fact_ledger": facts.model_dump(mode="json"),
            "asset_inventory": [
                asset.model_dump(mode="json") for asset in assets
            ],
            "current_email_design": email_design.model_dump(mode="json"),
            "design_critique": design_critique.model_dump(mode="json"),
            "allowed_asset_ids": [
                asset.asset_id for asset in assets
            ],
            "authoritative_destination_url": (
                facts.authoritative_destination_url
            ),
        }
        return (
            EMAIL_DESIGN_REVISION_PROMPT
            + "\n\nINPUT JSON:\n"
            + json.dumps(payload, ensure_ascii=False)
        )

    def _critique_design(
        self,
        *,
        brand: BrandProfile,
        reference: ReferenceDesignSpec,
        assets: list[AssetDescriptor],
        email_design: EmailDesign,
    ) -> tuple[DesignCritique, dict]:
        render_result = render_email_to_mjml(
            brand_profile=brand.model_dump(mode="json"),
            email_design=email_design.model_dump(mode="json"),
            asset_inventory=[
                asset.model_dump(mode="json")
                for asset in assets
            ],
        )
        compile_result = compile_mjml_to_html(render_result["mjml"])
        screenshot = capture_email_screenshot(
            compile_result["html"],
            asset_urls=[asset.url for asset in assets],
        )
        critique_payload = self.critic.critique(
            screenshot_base64=screenshot["image_base64"],
            screenshot_mime_type=screenshot["mime_type"],
            brand_profile=brand.model_dump(mode="json"),
            email_design=email_design.model_dump(mode="json"),
            reference_design_spec=reference.model_dump(mode="json"),
            asset_inventory=[
                asset.model_dump(mode="json")
                for asset in assets
            ],
            render_metadata={
                "width": screenshot["width"],
                "height": screenshot["height"],
                "rendered_sections": render_result["rendered_sections"],
                "available_asset_ids": render_result[
                    "available_asset_ids"
                ],
                "image_diagnostics": screenshot["image_diagnostics"],
            },
        )
        return DesignCritique.model_validate(critique_payload), {
            "render_metadata": {
                "width": screenshot["width"],
                "height": screenshot["height"],
                "mime_type": screenshot["mime_type"],
                "image_diagnostics": screenshot["image_diagnostics"],
            },
            "compiler_errors": compile_result["compiler_errors"],
        }

    def revise(
        self,
        *,
        brand_profile: dict,
        reference_design_spec: dict,
        content_plan: dict,
        fact_ledger: dict,
        asset_inventory: list[dict],
        email_design: dict,
        design_critique: dict | None = None,
        max_revision_attempts: int | None = None,
        include_diagnostics: bool = False,
    ) -> dict:
        try:
            brand = BrandProfile.model_validate(brand_profile)
            reference = ReferenceDesignSpec.model_validate(
                reference_design_spec
            )
            plan = ContentPlan.model_validate(content_plan)
            facts = FactLedger.model_validate(fact_ledger)
            assets = [
                AssetDescriptor.model_validate(item)
                for item in asset_inventory
            ]
            current_design = normalize_email_design(
                EmailDesign.model_validate(email_design),
                asset_inventory=assets,
                fact_ledger=facts,
            )
            max_attempts = self._bounded_max_attempts(
                max_revision_attempts
            )
        except ValidationError as exc:
            raise EmailDesignRevisionError(
                "Invalid input contract for EmailDesign revision.",
                details=str(exc),
            ) from exc

        diagnostics: dict = {
            "max_revision_attempts": max_attempts,
            "attempts": [],
        }

        try:
            if design_critique is not None:
                current_critique = DesignCritique.model_validate(
                    design_critique
                )
                critique_metadata = {}
            else:
                current_critique, critique_metadata = self._critique_design(
                    brand=brand,
                    reference=reference,
                    assets=assets,
                    email_design=current_design,
                )
                diagnostics["initial_critique"] = critique_metadata
        except (
            DesignCritiqueError,
            EmailRenderInputError,
            MJMLCompilerError,
            EmailScreenshotError,
            ValidationError,
        ) as exc:
            raise EmailDesignRevisionError(
                "Could not establish the initial visual critique.",
                details=str(exc),
            ) from exc

        if not current_critique.revision_needed:
            response = {
                "email_design": current_design.model_dump(mode="json"),
                "design_critique": current_critique.model_dump(mode="json"),
                "revision_notes": [],
                "attempts_used": 0,
                "max_attempts": max_attempts,
                "terminated_reason": "no_revision_needed",
                "completed": True,
            }
            if include_diagnostics:
                response["developer_diagnostics"] = diagnostics
            return response

        last_valid_design = current_design
        attempts_used = 0

        for attempt in range(1, max_attempts + 1):
            attempts_used = attempt
            prompt = self._build_revision_prompt(
                brand=brand,
                reference=reference,
                plan=plan,
                facts=facts,
                assets=assets,
                email_design=last_valid_design,
                design_critique=current_critique,
            )

            try:
                output_text = self._request_revised_design(prompt)
                revised_design, recovery_actions = (
                    self._validate_and_normalize_revised_design(
                        output_text,
                        content_plan=plan,
                        fact_ledger=facts,
                        assets=assets,
                    )
                )
                last_valid_design = revised_design
                next_critique, critique_metadata = self._critique_design(
                    brand=brand,
                    reference=reference,
                    assets=assets,
                    email_design=revised_design,
                )
            except (
                DesignCritiqueError,
                EmailRenderInputError,
                MJMLCompilerError,
                EmailScreenshotError,
                ValidationError,
                ValueError,
                TypeError,
            ) as exc:
                response = {
                    "email_design": last_valid_design.model_dump(mode="json"),
                    "design_critique": current_critique.model_dump(
                        mode="json"
                    ),
                    "revision_notes": [],
                    "attempts_used": attempts_used,
                    "max_attempts": max_attempts,
                    "terminated_reason": "critic_failed",
                    "completed": False,
                }
                if include_diagnostics:
                    diagnostics["attempts"].append(
                        {
                            "attempt": attempt,
                            "failure": str(exc),
                        }
                    )
                    response["developer_diagnostics"] = diagnostics
                return response

            current_critique = next_critique
            diagnostics["attempts"].append(
                {
                    "attempt": attempt,
                    "recovery_actions": recovery_actions,
                    "render_metadata": critique_metadata["render_metadata"],
                    "compiler_errors": critique_metadata["compiler_errors"],
                    "revision_needed_after_attempt": (
                        next_critique.revision_needed
                    ),
                }
            )

            if not next_critique.revision_needed:
                response = {
                    "email_design": last_valid_design.model_dump(mode="json"),
                    "design_critique": next_critique.model_dump(mode="json"),
                    "revision_notes": [
                        f"Revision completed in {attempt} attempt(s)."
                    ],
                    "attempts_used": attempts_used,
                    "max_attempts": max_attempts,
                    "terminated_reason": "approved",
                    "completed": True,
                }
                if include_diagnostics:
                    response["developer_diagnostics"] = diagnostics
                return response

        response = {
            "email_design": last_valid_design.model_dump(mode="json"),
            "design_critique": current_critique.model_dump(mode="json"),
            "revision_notes": [
                (
                    "Revision stopped at the configured maximum attempts "
                    f"({max_attempts})."
                )
            ],
            "attempts_used": attempts_used,
            "max_attempts": max_attempts,
            "terminated_reason": "max_attempts_reached",
            "completed": True,
        }
        if include_diagnostics:
            response["developer_diagnostics"] = diagnostics
        return response
