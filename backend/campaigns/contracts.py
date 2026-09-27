from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from email_generation.schemas import AssetKind, EmailDesign


class CampaignGatewayExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class PromotedAssetRef(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)
    asset_record_id: UUID
    kind: AssetKind
    public_url: str = Field(min_length=1, max_length=4096)


class AssetPromotionResult(BaseModel):
    assets: list[PromotedAssetRef] = Field(default_factory=list)
    unresolved_asset_ids: list[str] = Field(default_factory=list)


class DesignRevisionResult(BaseModel):
    email_design: EmailDesign
    revision_notes: list[str] = Field(default_factory=list)


class AudienceSnapshotContract(BaseModel):
    snapshot_id: UUID
    recipient_count: int = Field(ge=0)
    excluded_count: int = Field(default=0, ge=0)
    selection: dict = Field(default_factory=dict)


class DeliveryJobContract(BaseModel):
    job_id: str = Field(min_length=1, max_length=200)
    mode: Literal["send_now", "scheduled"]
    status: Literal["queued", "scheduled", "sending"]
    scheduled_for: datetime | None = None

    @model_validator(mode="after")
    def scheduled_job_requires_time(self):
        if self.mode == "scheduled" and self.scheduled_for is None:
            raise ValueError(
                "scheduled_for is required for a scheduled delivery job."
            )
        return self


class DeliverySummaryContract(BaseModel):
    total: int = Field(ge=0)
    queued: int = Field(default=0, ge=0)
    sent: int = Field(default=0, ge=0)
    delivered: int = Field(default=0, ge=0)
    bounced: int = Field(default=0, ge=0)
    complained: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    last_event_at: datetime | None = None


class AssetPromotionGateway(Protocol):
    def promote_campaign_assets(
        self,
        *,
        campaign_id: UUID,
        assets: list[dict],
    ) -> AssetPromotionResult | dict:
        ...


class DesignRevisionGateway(Protocol):
    def revise_campaign_design(
        self,
        *,
        campaign_id: UUID,
        brand_profile: dict,
        campaign_brief: dict,
        reference: dict,
        content_plan: dict,
        fact_ledger: dict,
        email_design: dict,
        instruction: str,
    ) -> DesignRevisionResult | dict:
        ...


class AudienceGateway(Protocol):
    def resolve_campaign_audience(
        self,
        *,
        campaign_id: UUID,
        owner_id: int,
        selection: dict,
    ) -> AudienceSnapshotContract | dict:
        ...


class DeliveryGateway(Protocol):
    def create_campaign_delivery(
        self,
        *,
        campaign_id: UUID,
        audience_snapshot_id: UUID,
        subject: str,
        html: str,
        mode: Literal["send_now", "scheduled"],
        scheduled_for: datetime | None,
        idempotency_key: str | None,
    ) -> DeliveryJobContract | dict:
        ...

    def get_campaign_delivery_summary(
        self,
        *,
        campaign_id: UUID,
    ) -> DeliverySummaryContract | dict:
        ...
