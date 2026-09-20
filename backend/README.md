# Yo-kai Mail Backend

This backend is the orchestration layer for Yo-kai Mail.

## Phase 1 progress

The current working pipeline is:

```text
Website URL
    -> Firecrawl
    -> WebsiteSnapshot
    -> Gemini
    -> BrandProfile

CampaignBrief
```

### 1. Website intelligence

```text
POST /api/website/import/
```

Input:

```json
{
  "url": "https://example.com"
}
```

This returns Yo-kai Mail's normalized `WebsiteSnapshot`.

### 2. Brand intelligence

```text
POST /api/brand/analyze/
```

Input:

```json
{
  "snapshot": {
    "...": "paste the WebsiteSnapshot data object here"
  }
}
```

This returns a validated `BrandProfile` containing:

- canonical brand identity
- email-usable color palette
- typography
- visual style keywords
- tone and copy characteristics
- deterministic logo/hero candidates
- confidence score

Gemini uses structured JSON output validated by Pydantic. Website content is
treated as untrusted evidence, and asset URLs are bound from WebsiteSnapshot by
application code instead of allowing the model to invent them.

## Local setup

From `backend/`:

```powershell
uv sync
```

Make sure your local `.env` contains:

```text
FIRECRAWL_API_KEY=...
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.8-flash
```

Never commit `.env`.

Run:

```powershell
uv run python manage.py test
uv run python manage.py runserver
```

Swagger:

```text
http://127.0.0.1:8000/api/docs/swagger/
```

## Current V0 limitation

The Brand Intelligence service includes the screenshot URL in its evidence, but
does not yet download and send the screenshot bytes as multimodal Gemini input.
The base text/structured-evidence pipeline should be proven first. Screenshot
vision can be added afterward by the Brand Intelligence owner.

## Team boundaries

```text
website_intelligence/
    URL -> WebsiteSnapshot

brand_intelligence/
    WebsiteSnapshot -> BrandProfile

future email_generation/
    BrandProfile + CampaignBrief -> EmailDesign

future rendering/
    EmailDesign -> MJML -> HTML

future delivery/
    HTML -> DeliveryResult
```


## 3. Campaign brief

```text
POST /api/campaigns/brief/
```

This checkpoint captures user intent as a stable `CampaignBrief` before any
email-generation AI is called.

Example:

```json
{
  "campaign_type": "product_launch",
  "goal": "drive_sales",
  "audience": {
    "description": "Existing luxury customers"
  },
  "product": {
    "name": "Speedy Bandouliere 20",
    "url": "https://example.com/products/speedy"
  },
  "destination_url": "https://example.com/products/speedy",
  "additional_instructions": "Keep the copy minimal and refined."
}
```

The API validates and normalizes this into:

```text
CampaignBrief
```

No Gemini call, persistence, or email rendering happens in this checkpoint.

The next generation stage will consume:

```text
BrandProfile
+
CampaignBrief
+
ReferenceDesignSpec or DesignRecipe
+
AssetLibrary
    -> ContentPlan
    -> EmailDesign
```


## 4. Reference design analyzer

```text
POST /api/reference-design/analyze/
Content-Type: multipart/form-data
```

Upload one reference marketing-email screenshot as the `image` field.

Supported V0 image types:

- JPEG
- PNG
- WebP
- maximum 15 MB

The endpoint sends the image to Gemini as multimodal input and returns a
schema-validated `ReferenceDesignSpec`.

The purpose is to reverse-engineer reusable composition, not copy the original
brand. The spec contains:

- email archetype
- visual hierarchy
- section sequence
- structural copy formula
- CTA rhythm
- spacing rhythm
- design rules
- reusable principles
- brand-specific elements that should be ignored during adaptation
- confidence

The next generation stage will combine:

```text
BrandProfile
+
CampaignBrief
+
ReferenceDesignSpec
+
AssetLibrary
    -> ContentPlan
    -> EmailDesign
```


### Separate Gemini model for reference analysis

Reference-image analysis uses its own model setting:

```text
GEMINI_REFERENCE_MODEL=gemini-3.1-flash-lite
```

This keeps high-volume visual/reference analysis separate from the main
`GEMINI_MODEL` used by Brand Intelligence. It also lets each subsystem be
tuned for cost, latency, and quota independently.

If a provider rate limit is reached, the reference-design endpoint returns HTTP
429 instead of reporting it as a generic 502 provider failure.


## 5. Curated internal reference library

When a user does not upload a design reference, Yo-kai Mail can choose a
curated internal design direction without making another AI request.

```text
BrandProfile
+
CampaignBrief
    -> deterministic Reference Selector
    -> internal reference
    -> ReferenceDesignSpec
```

Endpoints:

```text
GET  /api/reference-library/
POST /api/reference-library/select/
```

The selector considers:

- campaign type
- campaign goal
- brand industry
- brand tone
- whether an offer exists
- whether a product is defined
- whether the currently available image assets can support the layout

The selected result uses the same `ReferenceDesignSpec` contract as a
user-uploaded reference. This means downstream generation does not need to know
where the design direction came from.

Current V0 library families include:

- luxury editorial product launch
- seasonal collection showcase
- feature-led product launch
- bold promotional sale
- lifestyle story
- educational / benefit-led
- catalog promotion
- general brand story

These are reusable structural directions. They are not pixel copies of third-
party email creatives, and target-brand assets, colors, copy, and identity must
come from Yo-kai Mail's own brand/campaign inputs.


## 6. Checkpoint 7A — Campaign Strategist / ContentPlan

The first half of Checkpoint 7 converts the stable intelligence inputs into a
campaign strategy contract before final email copy/layout is composed.

```text
BrandProfile
+
CampaignBrief
+
ReferenceDesignSpec
+
available assets
    -> Campaign Strategist
    -> ContentPlan
```

Endpoint:

```text
POST /api/email-generation/plan/
```

The request accepts `brand_profile`, `campaign_brief`,
`reference_design_spec`, and optional `available_assets`.

If `available_assets` is omitted, the backend creates a temporary asset
inventory from BrandProfile assets. This is a bridge until the full AssetLibrary
subsystem is implemented.

Reliability boundaries:

- Gemini does not generate HTML or MJML.
- CTA destination URLs are rebound from CampaignBrief after generation.
- AI-produced asset IDs are filtered against the real asset inventory.
- Unsupported product claims are explicitly forbidden by the strategist prompt.
- Provider quota failures return HTTP 429 when detected.

Checkpoint 7B will consume ContentPlan and produce EmailDesign. The EmailDesign
v1 schema is already defined in `email_generation/schemas.py`.


## 7. Checkpoint 7B — Email Design Composer

The second half of Checkpoint 7 converts approved campaign strategy into a
structured, renderer-ready EmailDesign.

```text
BrandProfile
+
ContentPlan
+
ReferenceDesignSpec
+
AssetInventory
+
FactLedger
    -> Email Design Composer
    -> EmailDesign
```

Endpoint:

```text
POST /api/email-generation/design/
```

The composer produces:

- final subject
- preheader
- theme roles
- ordered sections
- final section copy
- asset references by asset_id
- CTA labels and layout choices

It still does NOT produce HTML, MJML, or CSS.

FactLedger is application-owned evidence built from validated campaign inputs.
The composer is instructed to keep concrete product and offer claims inside this
ledger. Application code also:

- filters invented asset IDs
- rebinds every CTA URL to the authoritative destination
- normalizes section order
- guarantees unique section IDs

The next checkpoint will render EmailDesign deterministically into MJML and
HTML.


## 8. Checkpoint 8A — Deterministic MJML Rendering

Checkpoint 8 removes AI from the rendering step.

```text
BrandProfile
+
EmailDesign
+
AssetInventory
    -> deterministic renderer
    -> MJML
```

Endpoint:

```text
POST /api/email-rendering/mjml/
```

The renderer:

- validates BrandProfile and EmailDesign contracts
- resolves semantic color/font/content-width roles
- maps asset IDs to real URLs
- renders supported EmailDesign section types into MJML
- escapes recipient-facing copy before inserting it into markup
- allows only HTTP/HTTPS image and CTA URLs
- does not call an AI provider

Checkpoint 8B will compile the validated MJML into responsive HTML using the
official MJML compiler. Keeping 8A and 8B separate makes renderer bugs and
compiler/runtime bugs independently testable.


## 9. Checkpoint 8B — Responsive HTML Compilation

The HTML endpoint keeps the same request contract as the MJML endpoint:

```text
BrandProfile
+
EmailDesign
+
AssetInventory
    -> deterministic MJML renderer
    -> local official MJML compiler
    -> responsive HTML
```

Install the pinned compiler once from `backend/`:

```powershell
cd mjml_runtime
npm install
cd ..
```

Endpoint:

```text
POST /api/email-rendering/html/
```

The backend calls the local `mjml_runtime/compile.mjs` process with MJML over
stdin and receives HTML over stdout. Runtime downloads are never performed
during a render.

Environment defaults:

```text
MJML_NODE_BINARY=node
MJML_COMPILE_TIMEOUT_SECONDS=10
```

The endpoint returns the compiled HTML, the intermediate MJML, compiler errors,
the resolved theme, rendered section count, and available asset IDs. The local
compiler uses strict MJML validation.


## 10. Checkpoint 9A — Browser Screenshot

Checkpoint 9 begins visual QA. The first stage renders the final responsive HTML
inside a real headless Chromium browser and captures the full email as PNG.

```text
BrandProfile
+
EmailDesign
+
AssetInventory
    -> MJML
    -> responsive HTML
    -> headless Chromium
    -> PNG screenshot
```

Python Playwright is used for browser orchestration. After pulling this
checkpoint, install dependencies and the Chromium runtime once:

```powershell
uv sync
uv run playwright install chromium
```

Endpoint:

```text
POST /api/email-rendering/screenshot/
```

The request body is identical to the MJML and HTML rendering endpoints.

The response contains:

- PNG bytes encoded as base64
- MIME type
- rendered browser width and full-page height
- MJML compiler errors
- rendered section count
- available asset IDs

The screenshot browser does not receive unrestricted network access. Remote
requests are restricted to public hosts represented in the provided
AssetInventory; localhost and private-network destinations are rejected.

The next stage, Checkpoint 9B, will give the rendered screenshot and design
reference to a structured visual Design Critic.


## 11. Checkpoint 9B — Structured Visual Design Critic

Checkpoint 9B keeps the screenshot inside the backend and sends it to a
multimodal design critic together with the structured design context.

```text
BrandProfile
+
EmailDesign
+
ReferenceDesignSpec
+
AssetInventory
    -> deterministic MJML
    -> responsive HTML
    -> Chromium screenshot
    -> multimodal Design Critic
    -> DesignCritique
```

Endpoint:

```text
POST /api/email-visual-qa/critique/
```

Request fields:

- `brand_profile`
- `email_design`
- `reference_design_spec`
- optional `asset_inventory`

The screenshot is regenerated internally. Clients do not need to send the large
base64 PNG produced by the screenshot debugging endpoint.

The critic returns a schema-validated `DesignCritique` containing:

- whether a meaningful revision is needed
- a short visual summary
- visible strengths
- structured issues with category, severity, affected section IDs, observation,
  reason, and an actionable EmailDesign-level recommendation
- prioritized visual changes

The critic is explicitly limited to visual/design feedback. It must not generate
HTML/MJML/CSS or invent/fact-check product claims.

The critic model is configured separately:

```text
GEMINI_CRITIC_MODEL=gemini-3.1-flash-lite
```

Checkpoint 9C will consume `DesignCritique` and create one bounded revised
EmailDesign. The revision loop will have a hard maximum iteration count.


### Image-load validation before critique

Visual critique is only meaningful when the browser rendered the assets
successfully. Before a screenshot is accepted, Yo-kai Mail now inspects every
rendered `<img>` element.

A valid screenshot must report:

```json
{
  "image_diagnostics": {
    "total": 1,
    "loaded": 1,
    "broken": []
  }
}
```

If any rendered image has zero natural width or fails to complete, screenshot
capture raises an error and the Design Critic is not called. Public CDN redirect
targets are permitted, while localhost, private, link-local, multicast, reserved,
and unspecified network destinations remain blocked.
