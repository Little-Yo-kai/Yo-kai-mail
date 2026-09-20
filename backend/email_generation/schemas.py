from typing import Literal

from pydantic import BaseModel, Field, model_validator


AssetKind = Literal[
    "logo",
    "hero",
    "product",
    "detail",
    "lifestyle",
    "og",
    "other",
]


class AssetDescriptor(BaseModel):
    asset_id: str
    kind: AssetKind
    url: str
    source: Literal["brand_profile", "asset_library", "request"]


class FactLedger(BaseModel):
    brand_name: str | None = None
    product_name: str | None = None
    verified_facts: list[str] = Field(default_factory=list)
    offer_facts: list[str] = Field(default_factory=list)
    authoritative_destination_url: str | None = None
    forbidden_claim_categories: list[str] = Field(default_factory=list)


class ContentBeat(BaseModel):
    order: int = Field(ge=1)
    role: Literal[
        "emotional_hook",
        "campaign_context",
        "product_story",
        "product_feature",
        "benefit",
        "craftsmanship",
        "offer",
        "urgency",
        "lifestyle",
        "social_proof",
        "cta",
        "footer",
    ]
    objective: str
    key_message: str
    recommended_section_type: Literal[
        "hero",
        "intro",
        "product_feature",
        "product_grid",
        "benefits",
        "lifestyle",
        "offer",
        "cta",
        "footer",
    ]
    preferred_asset_role: Literal[
        "hero",
        "product",
        "detail",
        "lifestyle",
        "logo",
        "none",
    ]


class CTAPlan(BaseModel):
    primary_action: str
    destination_url: str | None = None
    frequency: Literal["low", "medium", "high"]
    placement_strategy: str
    tone: str


class AssetNeed(BaseModel):
    purpose: str
    preferred_kind: AssetKind | Literal["none"]
    candidate_asset_ids: list[str] = Field(default_factory=list)
    required: bool


class CopyStrategy(BaseModel):
    tone: list[str]
    density: Literal["low", "medium", "high"]
    sentence_style: str
    emphasis_style: str
    avoid: list[str] = Field(default_factory=list)


class ReferenceAdaptation(BaseModel):
    principles_to_preserve: list[str] = Field(default_factory=list)
    elements_to_avoid_copying: list[str] = Field(default_factory=list)
    adaptation_notes: list[str] = Field(default_factory=list)


class ContentPlan(BaseModel):
    schema_version: str = "1.0"
    campaign_angle: str
    strategic_rationale: str
    audience_focus: str
    primary_message: str
    supporting_messages: list[str] = Field(min_length=1, max_length=4)
    subject_line_angles: list[str] = Field(min_length=2, max_length=4)
    preheader_direction: str
    content_hierarchy: list[ContentBeat] = Field(min_length=1)
    cta_strategy: CTAPlan
    copy_strategy: CopyStrategy
    asset_strategy: list[AssetNeed] = Field(default_factory=list)
    reference_adaptation: ReferenceAdaptation
    claim_constraints: list[str] = Field(default_factory=list)




def _has_text(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_meaningful_items(items: list["EmailSectionItem"]) -> bool:
    return any(
        _has_text(item.title)
        or _has_text(item.body)
        or item.asset_id is not None
        or item.cta is not None
        for item in items
    )


class EmailCTA(BaseModel):
    label: str
    url: str | None = None


class EmailSectionItem(BaseModel):
    title: str | None = None
    body: str | None = None
    asset_id: str | None = None
    cta: EmailCTA | None = None


class SectionStyle(BaseModel):
    alignment: Literal["left", "center", "right"]
    spacing: Literal["compact", "balanced", "generous", "very_generous"]
    background_role: Literal[
        "brand_background",
        "primary",
        "secondary",
        "accent",
        "neutral",
        "image",
        "transparent",
    ]


class EmailSection(BaseModel):
    id: str
    order: int = Field(ge=1)
    type: Literal[
        "hero",
        "intro",
        "product_feature",
        "product_grid",
        "benefits",
        "lifestyle",
        "offer",
        "cta",
        "divider",
        "footer",
    ]
    layout: Literal[
        "full_width",
        "centered",
        "split_image_left",
        "split_image_right",
        "grid_2",
        "grid_3",
        "stacked",
        "minimal",
    ]
    eyebrow: str | None = None
    headline: str | None = None
    body: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    items: list[EmailSectionItem] = Field(default_factory=list)
    cta: EmailCTA | None = None
    style: SectionStyle

    @model_validator(mode="after")
    def validate_section_content(self):
        if self.type == "hero" and not _has_text(self.headline):
            raise ValueError("Hero sections require a headline.")

        if self.type in {"intro", "lifestyle", "offer"}:
            if not _has_text(self.body):
                raise ValueError(
                    f"{self.type} sections require final body copy."
                )

        if self.type == "product_feature":
            if not _has_text(self.body) and not _has_meaningful_items(self.items):
                raise ValueError(
                    "Product feature sections require body copy or populated items."
                )

        if self.type == "benefits":
            if not _has_text(self.body) and not _has_meaningful_items(self.items):
                raise ValueError(
                    "Benefits sections require body copy or populated items."
                )

        if self.type == "product_grid" and not _has_meaningful_items(self.items):
            raise ValueError(
                "Product grid sections require populated items."
            )

        if self.type == "cta" and self.cta is None:
            raise ValueError("CTA sections require a CTA object.")

        return self


class EmailTheme(BaseModel):
    content_width: Literal["narrow", "standard", "wide"]
    heading_font_role: Literal["brand_heading", "brand_body", "system"]
    body_font_role: Literal["brand_body", "brand_heading", "system"]
    primary_color_role: Literal["primary", "secondary", "accent", "text_primary"]
    background_color_role: Literal[
        "background",
        "primary",
        "secondary",
        "neutral",
    ]
    button_color_role: Literal["primary", "secondary", "accent", "text_primary"]


class EmailDesign(BaseModel):
    schema_version: str = "1.0"
    subject: str
    preheader: str
    theme: EmailTheme
    sections: list[EmailSection] = Field(min_length=1)
