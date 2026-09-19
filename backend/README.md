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
