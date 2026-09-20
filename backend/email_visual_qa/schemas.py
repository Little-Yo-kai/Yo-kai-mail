from typing import Literal

from pydantic import BaseModel, Field


class DesignCritiqueIssue(BaseModel):
    category: Literal[
        "hierarchy",
        "imagery",
        "spacing",
        "typography",
        "color",
        "cta",
        "density",
        "reference_alignment",
        "section_flow",
        "accessibility",
    ]
    severity: Literal["minor", "major"]
    affected_section_ids: list[str] = Field(default_factory=list)
    observation: str
    why_it_matters: str
    recommended_change: str


class DesignCritique(BaseModel):
    schema_version: str = "1.0"
    revision_needed: bool
    summary: str
    strengths: list[str] = Field(default_factory=list, max_length=5)
    issues: list[DesignCritiqueIssue] = Field(default_factory=list, max_length=8)
    priority_changes: list[str] = Field(default_factory=list, max_length=5)
