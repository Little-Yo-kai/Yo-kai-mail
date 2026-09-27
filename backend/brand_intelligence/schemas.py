from typing import Literal

from pydantic import BaseModel, Field


class BrandIdentity(BaseModel):
    name: str = Field(description="Canonical brand or company name.")
    description: str | None = None
    industry: str | None = None


class BrandColors(BaseModel):
    primary: str | None = None
    secondary: str | None = None
    accent: str | None = None
    background: str | None = None
    text_primary: str | None = None


class BrandTypography(BaseModel):
    heading_family: str | None = None
    body_family: str | None = None


class BrandVisual(BaseModel):
    color_scheme: Literal["light", "dark", "mixed", "unknown"] = "unknown"
    colors: BrandColors
    typography: BrandTypography
    style_keywords: list[str] = Field(default_factory=list)
    border_radius: str | None = None


class CopyCharacteristics(BaseModel):
    sentence_length: Literal["short", "medium", "long", "mixed"] = "mixed"
    emoji_usage: Literal["none", "low", "medium", "high"] = "none"
    formality: Literal["low", "medium", "high"] = "medium"


class BrandCommunication(BaseModel):
    tone: list[str] = Field(default_factory=list)
    copy_characteristics: CopyCharacteristics


class BrandAnalysis(BaseModel):
    identity: BrandIdentity
    visual: BrandVisual
    communication: BrandCommunication
    confidence: float = Field(ge=0.0, le=1.0)


class BrandAssets(BaseModel):
    primary_logo: str | None = None
    hero_candidates: list[str] = Field(default_factory=list)
    og_image: str | None = None
    favicon: str | None = None


class BrandProfile(BaseModel):
    schema_version: str = "1.0"
    identity: BrandIdentity
    visual: BrandVisual
    communication: BrandCommunication
    assets: BrandAssets
    confidence: float = Field(ge=0.0, le=1.0)
