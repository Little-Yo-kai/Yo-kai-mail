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
