# Yo-kai Mail Backend

This backend is the orchestration layer for Yo-kai Mail.

## Current checkpoint

Checkpoint 2 now proves this path:

```text
POST website URL
      -> Django / DRF
      -> Firecrawl
      -> raw provider response
      -> WebsiteSnapshot normalizer
      -> stable Yo-kai Mail JSON response
```

The application no longer exposes Firecrawl's complete provider-shaped response
as its internal contract. Instead, the response is normalized into a
`WebsiteSnapshot`.

## Why WebsiteSnapshot exists

Firecrawl is an extraction provider, not the source of truth for our product.

For example, an extractor may mistake a product page title for the company brand
or classify a modal button as the site's primary CTA. The snapshot therefore
stores fields such as `brand_name_candidate` as observed evidence. In the next
checkpoint, Gemini will interpret this evidence to produce a `BrandProfile`.

## Local setup (Windows PowerShell)

From the `backend` directory:

```powershell
uv sync
Copy-Item .env.example .env
```

Open `.env` and set your own Firecrawl key:

```text
FIRECRAWL_API_KEY=fc-your-key-here
```

Then run:

```powershell
uv run python manage.py migrate
uv run python manage.py test
uv run python manage.py runserver
```

## Test the endpoint

Send:

```http
POST http://127.0.0.1:8000/api/website/import/
Content-Type: application/json
```

Body:

```json
{
  "url": "https://example.com"
}
```

The response now has this high-level shape:

```json
{
  "success": true,
  "data": {
    "schema_version": "1.0",
    "source": {},
    "content": {},
    "visual": {},
    "assets": {},
    "detected_branding": {},
    "extraction": {}
  }
}
```

## WebsiteSnapshot sections

- `source`: requested/resolved URL and page metadata
- `content`: extracted public text/markdown
- `visual`: screenshot evidence
- `assets`: public image URLs and logo/favicon/OG candidates
- `detected_branding`: provider-detected visual/style evidence
- `extraction`: provider/debug metadata

## Swagger

With the server running:

```text
http://127.0.0.1:8000/api/docs/swagger/
```

## Important

- Never commit `.env`.
- `detected_branding` contains evidence, not authoritative brand truth.
- The current URL validation is sufficient for this local proof-of-pipeline checkpoint, but it is not production-grade SSRF protection.
- Do not add Gemini, MJML, the visual editor, or campaign logic until this checkpoint works.
