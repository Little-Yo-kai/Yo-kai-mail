# Yo-kai Mail Backend

This backend is the orchestration layer for Yo-kai Mail.

## Current checkpoint

Checkpoint 1 proves this path:

```text
POST website URL
      -> Django / DRF
      -> Firecrawl
      -> Django JSON response
```

The Firecrawl response is intentionally returned mostly as-is in this checkpoint.
The next checkpoint will normalize it into the internal `WebsiteSnapshot` contract.

## Local setup (Windows PowerShell)

From the `backend` directory:

```powershell
uv sync
Copy-Item .env.example .env
```

Open `.env` and replace:

```text
FIRECRAWL_API_KEY=fc-your-key-here
```

with your own Firecrawl API key.

Then run:

```powershell
uv run python manage.py migrate
uv run python manage.py test website_intelligence
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

A successful response has the shape:

```json
{
  "success": true,
  "data": {
    "...": "Firecrawl response"
  }
}
```

## Swagger

With the server running:

```text
http://127.0.0.1:8000/api/docs/swagger/
```

## Important

- Never commit `.env`.
- The current URL validation is sufficient for this local proof-of-pipeline checkpoint, but it is not production-grade SSRF protection.
- Do not add Gemini, MJML, the visual editor, or campaign logic until this checkpoint works.
