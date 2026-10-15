"""Connect the bounded visual revision service to campaign versioning."""

from campaigns.contracts import CampaignGatewayExecutionError
from core.provider_errors import is_provider_rate_limited

from .services.gemini import DesignCriticNotConfiguredError
from .services.revision import GeminiEmailDesignReviser


class CampaignDesignRevisionGateway:
    def revise_campaign_design(
        self,
        *,
        campaign_id,
        brand_profile,
        campaign_brief,
        reference,
        content_plan,
        fact_ledger,
        asset_inventory,
        email_design,
        instruction,
    ):
        try:
            result = GeminiEmailDesignReviser().revise(
                brand_profile=brand_profile,
                reference_design_spec=reference.get("reference_design_spec", reference),
                content_plan=content_plan,
                fact_ledger=fact_ledger,
                asset_inventory=asset_inventory,
                email_design=email_design,
                instruction=instruction,
            )
        except DesignCriticNotConfiguredError as exc:
            raise CampaignGatewayExecutionError(str(exc), retryable=True) from exc
        except Exception as exc:
            limited = is_provider_rate_limited(exc)
            raise CampaignGatewayExecutionError(
                "Visual revision is rate limited."
                if limited
                else "Visual revision failed.",
                retryable=limited,
                status_code=429 if limited else None,
            ) from exc

        # Do not version a fallback design as if a failed critic approved it.
        if not result.get("completed"):
            raise CampaignGatewayExecutionError(
                "Visual critique could not complete. The saved design is unchanged.",
                retryable=True,
            )
        return {
            "email_design": result["email_design"],
            "revision_notes": result.get("revision_notes", []),
        }
