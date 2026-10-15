from typing import Literal

from pydantic import BaseModel, Field, model_validator


FORBIDDEN_MARKUP_TOKENS = (
    "<html",
    "</html",
    "<body",
    "</body",
    "<style",
    "</style",
    "<script",
    "</script",
    "<mj",
    "</mj",
    "<table",
    "</table",
    "<div",
    "</div",
    "<span",
    "</span",
)


def _contains_forbidden_markup(value: str) -> bool:
    text = value.lower()
    return any(token in text for token in FORBIDDEN_MARKUP_TOKENS)


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

    @model_validator(mode="after")
    def validate_no_markup_payload(self):
        for value in (
            self.observation,
            self.why_it_matters,
            self.recommended_change,
        ):
            if _contains_forbidden_markup(value):
                raise ValueError(
                    "DesignCritique issues must not include HTML/CSS/MJML markup."
                )
        return self


class DesignCritique(BaseModel):
    schema_version: str = "1.0"
    revision_needed: bool
    summary: str
    strengths: list[str] = Field(default_factory=list, max_length=5)
    issues: list[DesignCritiqueIssue] = Field(default_factory=list, max_length=8)
    priority_changes: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_no_markup_payload(self):
        for value in [self.summary, *self.strengths, *self.priority_changes]:
            if _contains_forbidden_markup(value):
                raise ValueError(
                    "DesignCritique must not include HTML/CSS/MJML markup."
                )
        return self
