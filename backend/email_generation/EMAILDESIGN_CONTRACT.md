# EmailDesign contract compatibility

Friend 3 owns the structured EmailDesign boundary consumed by Friend 4 and Prajwal. Rendering is intentionally outside this contract.

## Supported versions

- 1.0 — existing Phase 1/2 structured design: subject, preheader, theme, and sections.
- 1.1 — adds alternative_subjects and content_variants. These fields are explicitly versioned; a 1.0 document must not contain them.

Consumers must accept both 1.0 and 1.1 while migrating. New generation uses 1.1 when alternatives or content variants are present. A consumer that only supports 1.0 must reject 1.1 explicitly rather than silently dropping fields.

## Compatibility rules

1. Unknown schema versions are rejected.
2. Required fields and section types remain Pydantic-validated.
3. Asset IDs must exist in the application-provided approved inventory.
4. CTA URLs must be valid HTTP(S) URLs and, when a FactLedger authoritative destination exists, must equal that destination.
5. Section regeneration replaces only the requested section. Top-level subject, preheader, theme, facts, CTA destinations, and all unrelated sections are preserved by application code.
6. Renderer/editor code must validate the complete document before use.
7. Schema changes require a new version plus compatibility tests.

## Friend 4 handoff

Friend 4 can consume the validated EmailDesign JSON directly. It should not need to know how Gemini was called, how recovery was performed, or how facts were selected. The renderer remains responsible for MJML/HTML only.
