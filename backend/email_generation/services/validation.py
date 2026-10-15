"""Application-owned validation for the EmailDesign contract.

This module deliberately sits between generation/editing and rendering. It
does not generate recipient-facing HTML/MJML and does not trust model output
for application-owned constraints.
"""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import ValidationError

from ..schemas import AssetDescriptor, EmailDesign, FactLedger


SUPPORTED_EMAIL_DESIGN_VERSIONS = {"1.0", "1.1"}
CURRENT_EMAIL_DESIGN_VERSION = "1.1"


class EmailDesignContractError(ValueError):
    """Raised when an EmailDesign cannot be safely consumed downstream."""


def _valid_http_url(value: str | None) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_email_design_contract(
    design: EmailDesign | dict,
    *,
    asset_inventory: list[AssetDescriptor | dict],
    fact_ledger: FactLedger | dict,
    require_current_version: bool = False,
) -> EmailDesign:
    """Validate the complete Friend 3 -> Friend 4 contract."""

    raw = design if isinstance(design, dict) else design.model_dump(mode="json")
    if not isinstance(raw, dict):
        raise EmailDesignContractError("EmailDesign payload must be an object.")

    version = raw.get("schema_version", "1.0")
    if version not in SUPPORTED_EMAIL_DESIGN_VERSIONS:
        raise EmailDesignContractError(
            f"Unsupported EmailDesign schema version: {version!r}."
        )

    if require_current_version and version != CURRENT_EMAIL_DESIGN_VERSION:
        raise EmailDesignContractError(
            f"EmailDesign schema version {version!r} is not current; "
            f"expected {CURRENT_EMAIL_DESIGN_VERSION!r}."
        )

    if version == "1.0":
        for field in ("alternative_subjects", "content_variants"):
            if field in raw:
                raise EmailDesignContractError(
                    f"{field} requires EmailDesign schema version 1.1."
                )

    try:
        validated = (
            design
            if isinstance(design, EmailDesign)
            else EmailDesign.model_validate(raw)
        )
    except ValidationError as exc:
        raise EmailDesignContractError(
            "Invalid structured EmailDesign output."
        ) from exc

    assets = [
        item if isinstance(item, AssetDescriptor)
        else AssetDescriptor.model_validate(item)
        for item in asset_inventory
    ]
    allowed_asset_ids = {asset.asset_id for asset in assets}
    facts = (
        fact_ledger
        if isinstance(fact_ledger, FactLedger)
        else FactLedger.model_validate(fact_ledger)
    )

    if not validated.subject.strip():
        raise EmailDesignContractError("EmailDesign.subject is required.")
    if not validated.preheader.strip():
        raise EmailDesignContractError("EmailDesign.preheader is required.")

    _validate_sections(validated.sections, allowed_asset_ids, facts)

    if validated.alternative_subjects:
        if version != "1.1":
            raise EmailDesignContractError(
                "alternative_subjects requires EmailDesign schema version 1.1."
            )
        if len(set(validated.alternative_subjects)) != len(
            validated.alternative_subjects
        ):
            raise EmailDesignContractError(
                "alternative_subjects must not contain duplicates."
            )

    if validated.content_variants:
        if version != "1.1":
            raise EmailDesignContractError(
                "content_variants requires EmailDesign schema version 1.1."
            )
        variant_ids = [variant.variant_id for variant in validated.content_variants]
        if len(set(variant_ids)) != len(variant_ids):
            raise EmailDesignContractError(
                "content_variants must have unique variant_id values."
            )
        for variant in validated.content_variants:
            if not variant.subject.strip() or not variant.preheader.strip():
                raise EmailDesignContractError(
                    f"Content variant {variant.variant_id!r} requires subject "
                    "and preheader."
                )
            _validate_sections(variant.sections, allowed_asset_ids, facts)

    return validated


def _validate_sections(sections, allowed_asset_ids: set[str], facts: FactLedger) -> None:
    section_ids: set[str] = set()
    for section in sections:
        if section.id in section_ids:
            raise EmailDesignContractError(
                f"Duplicate EmailDesign section id: {section.id!r}."
            )
        section_ids.add(section.id)

        unknown_assets = set(section.asset_ids) - allowed_asset_ids
        if unknown_assets:
            raise EmailDesignContractError(
                "Unapproved section asset IDs: "
                + ", ".join(sorted(unknown_assets))
            )

        if section.cta is not None:
            _validate_cta(section.cta.url, facts, section.id)

        for item in section.items:
            if item.asset_id is not None and item.asset_id not in allowed_asset_ids:
                raise EmailDesignContractError(
                    f"Unapproved asset ID in section {section.id!r}: "
                    f"{item.asset_id!r}."
                )
            if item.cta is not None:
                _validate_cta(item.cta.url, facts, section.id)


def _validate_cta(url: str | None, facts: FactLedger, section_id: str) -> None:
    if not _valid_http_url(url):
        raise EmailDesignContractError(
            f"CTA URL in section {section_id!r} must be a valid HTTP(S) URL."
        )

    authoritative = facts.authoritative_destination_url
    if authoritative and url.strip() != authoritative.strip():
        raise EmailDesignContractError(
            f"CTA URL in section {section_id!r} does not match the "
            "authoritative campaign destination."
        )
