from typing import Literal

from pydantic import BaseModel, Field


class VisualHierarchy(BaseModel):
    hero_dominance: Literal["low", "medium", "high", "very_high"]
    image_to_text_balance: Literal["image_heavy", "balanced", "text_heavy"]
    density: Literal["low", "medium", "high"]
    primary_alignment: Literal["left", "center", "right", "mixed"]


class ReferenceSection(BaseModel):
    order: int = Field(ge=1)
    type: Literal[
        "hero",
        "intro",
        "product_grid",
        "product_feature",
        "benefits",
        "lifestyle",
        "testimonial",
        "social_proof",
        "offer",
        "cta",
        "divider",
        "footer",
        "other",
    ]
    purpose: str
    layout: str
    alignment: Literal["left", "center", "right", "mixed"]
    image_usage: Literal["none", "supporting", "dominant", "background", "mixed"]
    copy_role: str


class CTAStyle(BaseModel):
    frequency: Literal["low", "medium", "high"]
    placement_pattern: str
    shape: Literal["rectangular", "rounded", "pill", "text_link", "mixed"]
    emphasis: Literal["subtle", "medium", "strong"]


class SpacingRhythm(BaseModel):
    overall: Literal["compact", "balanced", "generous", "very_generous"]
    section_separation: Literal["subtle", "medium", "strong"]


class DesignRules(BaseModel):
    background_strategy: str
    color_usage: str
    typography_behavior: str
    image_treatment: str
    mobile_behavior: str


class ReferenceDesignSpec(BaseModel):
    schema_version: str = "1.0"
    archetype: str
    summary: str
    visual_hierarchy: VisualHierarchy
    section_sequence: list[ReferenceSection] = Field(min_length=1)
    copy_formula: list[str] = Field(min_length=1)
    cta_style: CTAStyle
    spacing_rhythm: SpacingRhythm
    design_rules: DesignRules
    reusable_principles: list[str] = Field(min_length=1)
    brand_specific_elements_to_ignore: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
