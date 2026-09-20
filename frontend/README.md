# Yo-kai Mail — Phase 1 Demo Frontend

This frontend gives the current Phase 1 generation engine a real user-facing
workflow.

## What the demo supports

- website URL only
- optional reference marketing-email screenshot
- optional creative direction
- automatic internal reference selection when no image is uploaded
- generated subject and preheader
- desktop and mobile HTML preview
- open full preview
- download final HTML
- copy final HTML
- download MJML source

The UI intentionally does not expose internal JSON contracts or require Swagger.

## Run locally

Start the Django backend first from `backend/`.

Then from `frontend/`:

```powershell
npm install
npm run dev
```

The frontend defaults to:

```text
http://127.0.0.1:8000
```

for the backend API.

To override it, create `.env.local`:

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Open:

```text
http://localhost:3000
```

## Important demo limitation

Asset validation/stable hosting, visual critique, and the automatic revision loop
are intentionally bypassed in this demo flow. External website image URLs are
therefore rendered as discovered and some sites can block them through
hotlink/CDN protections. These items remain required before Phase 1 is complete.
