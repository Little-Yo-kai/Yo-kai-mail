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
- send generated HTML to one test inbox through Resend

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


## Test delivery

After an email is generated, enter a recipient address in the Resend Delivery
panel and choose **Send test email**. The browser sends only the recipient,
subject, and final compiled HTML to Django. Django owns the Resend credential and
performs the provider call.

The frontend must never contain `RESEND_API_KEY` or any equivalent secret.


The Phase 1 frontend intentionally supports **one test recipient at a time**.
After Resend accepts the email, the UI shows the provider message ID and lets
the user choose **Check delivery status** to retrieve the latest provider event.

This is deliberately not the campaign/bulk-send interface. The eventual campaign
flow will select contacts, lists, or segments and will apply unsubscribe,
suppression, deduplication, and delivery-job rules before sending.
