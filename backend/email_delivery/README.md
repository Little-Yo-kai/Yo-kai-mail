# Contacts and campaign delivery

This guide explains the contacts, audience, and email-delivery feature in
Yo-kai Mail. It covers the `/contacts` screen and the Django API behind it.

## What the feature does

- Imports contacts from a CSV and organizes them into contact lists.
- Tracks consent and unsubscribe/suppression status for each contact.
- Resolves selected lists and contacts into a saved campaign audience. It
  removes duplicates and excludes contacts without active, recorded consent.
- Keeps a one-recipient test email separate from campaign delivery.
- Queues campaign delivery immediately or schedules it for a future time using
  Celery and Redis.
- Records each recipient's Resend message ID and delivery events, then shows
  basic counts and recipient-level activity.

## Run it locally

You need Python dependencies installed with `uv`, Node.js for the frontend, a
Redis service for campaign jobs, and a Resend account if you want to send real
email.

### 1. Configure the backend

In PowerShell, from the repository root:

```powershell
cd backend
uv sync
Copy-Item .env.example .env
```

Edit `backend/.env` as needed. Set `RESEND_CAMPAIGN_SEND_ENABLED=True` only when
ready to enable actual campaign sending. For real sending, set `RESEND_API_KEY` and use a
sender address allowed by your Resend account. Keep this key in the backend; do
not put it in a frontend environment file. To receive delivery events, also set
`RESEND_WEBHOOK_SECRET` to the signing secret for your Resend webhook. The
default broker URL is `redis://127.0.0.1:6379/0`; make sure Redis is running at
that address or change `CELERY_BROKER_URL`.

Create the database tables and, if you do not already have an account, create a
Django login:

```powershell
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

Start Django in this terminal:

```powershell
uv run python manage.py runserver
```

### 2. Start the campaign worker

In another terminal, from `backend/`, start a Celery worker while Redis is
available:

```powershell
uv run celery -A core worker --pool=solo --loglevel=info
```

The worker is needed for campaign sends and scheduled delivery. Keep it running
so queued work can be processed. A Resend API key is required for actual sends.

### 3. Start the frontend

In a third terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000/contacts](http://localhost:3000/contacts) and sign
in with a Django account. The frontend does not provide account registration.
The API reference is available at
[http://127.0.0.1:8000/api/docs/swagger/](http://127.0.0.1:8000/api/docs/swagger/).

## Use the contacts screen

1. **Import contacts.** Download the CSV template from the screen, fill it in,
   and import it. The required column is `email`. Optional columns are
   `first_name`, `last_name`, `display_name`, `consent_status`, `consented_at`,
   `consent_source`, and `source`. CSV files can be up to 5 MB.
2. **Record permission.** A contact is eligible only when
   `consent_status` is `granted` and `consented_at` contains a valid ISO-8601
   timestamp, for example `2026-10-15T09:00:00Z`. Other contacts remain
   ineligible until valid consent is recorded.
3. **Organize and review.** Create a contact list, add imported contacts, and
   use the screen's search and filters. You can unsubscribe an active contact
   from the contact row.
4. **Choose a saved campaign.** In Campaign delivery, choose a campaign that
   has a saved design and has been reviewed and marked `ready`. The generation
   demo at `/` creates a preview, but does not save a campaign record for this
   delivery screen.
5. **Resolve the audience.** Select one or more lists and/or individual
   contacts, then choose **Resolve and save audience**. The screen reports how
   many eligible recipients will be included and how many contacts are excluded
   for status or missing consent. The saved snapshot is the audience
   used for sending.
6. **Send or schedule.** Choose **Send campaign now** or set a future local time
   and schedule it. A scheduled campaign can be canceled before delivery
   starts. The worker checks consent and suppression status again just before
   sending, so contacts who opt out after audience resolution are skipped.
7. **Review activity.** The campaign results area shows delivery counts,
   scheduled/job status, and recipient records. Resend events appear after the
   webhook is configured and Resend can reach its URL.

Campaign sends use the resolved audience; the campaign-send endpoints do not
accept a pasted list of email addresses. Each recipient is sent separately,
with a stable idempotency key to reduce duplicate sends during retries.

## Test emails

Test emails are for checking a design in one inbox. They are separate from
campaign sends and accept one recipient at a time. The generation demo can send
a rendered test email; a saved campaign also has a one-recipient test endpoint.
Test sending requires `RESEND_TEST_SEND_ENABLED=True` and a configured Resend
key. The frontend never receives the key.

## Resend webhook and delivery tracking

Configure a Resend webhook to send events to:

```text
https://your-host/api/email-delivery/webhooks/resend/
```

The URL must be reachable by Resend. Configure the matching signing secret as
`RESEND_WEBHOOK_SECRET` in the backend. The endpoint verifies Resend's Svix
signature against the raw request body and ignores duplicate event IDs.

Supported events include sent, delayed, delivered, bounced, failed, suppressed,
complained, opened, and clicked. Events are matched to the stored Resend message
ID for each campaign recipient. Bounce, complaint, and provider-suppression
events update that contact's status and withdraw consent. Open and click events
are recorded only when Resend tracking is enabled and sends those events; this
feature does not enable provider tracking by itself.

## API overview

Protected endpoints require a JWT access token in the `Authorization: Bearer`
header. Obtain a token at `POST /api/auth/token/`. Swagger lists request and
response schemas at `/api/docs/swagger/`.

| Purpose | Endpoint |
| --- | --- |
| List contacts | `GET /api/email-delivery/contacts/` |
| Import CSV contacts | `POST /api/email-delivery/contacts/import/` |
| Update a contact, including unsubscribe | `PATCH /api/email-delivery/contacts/{contact_id}/` |
| List or create contact lists | `GET` or `POST /api/email-delivery/contact-lists/` |
| View or add list members | `GET` or `POST /api/email-delivery/contact-lists/{list_id}/members/` |
| Send one test email | `POST /api/campaigns/{campaign_id}/send-test/` |
| Resolve and save audience | `POST /api/campaigns/{campaign_id}/audience/resolve/` |
| Queue immediate campaign delivery | `POST /api/campaigns/{campaign_id}/send/` |
| Schedule delivery | `POST /api/campaigns/{campaign_id}/schedule/` |
| Cancel a scheduled delivery | `POST /api/email-delivery/campaigns/{campaign_id}/cancel-schedule/` |
| Read provider-independent counts | `GET /api/campaigns/{campaign_id}/delivery-summary/` |
| Read job and paginated recipient activity | `GET /api/email-delivery/campaigns/{campaign_id}/activity/` |
| Receive Resend events | `POST /api/email-delivery/webhooks/resend/` |

For example, audience resolution accepts selected IDs:

```json
{
  "selection": {
    "list_ids": ["contact-list-uuid"],
    "contact_ids": ["contact-uuid"]
  }
}
```

Resolution returns `data.audience_snapshot` alongside `data.campaign`.
Send/schedule responses return `data.delivery_job` alongside `data.campaign`.

Scheduling accepts a future ISO-8601 timestamp:

```json
{
  "scheduled_for": "2026-11-01T09:00:00Z"
}
```

## Important constraints

- Contacts, lists, and campaigns are scoped to the signed-in account.
- Only a campaign with a persisted active design, a `ready` status, and a
  non-empty resolved audience can be sent or scheduled.
- A campaign can have only one non-canceled send job. Resolve the audience
  before creating that job; the audience is locked while a delivery job exists.
- The delivery screen needs a saved campaign. A generated preview alone is not
  a persisted campaign.
- Open and click tracking counts depend on Resend configuration and events.
- Do not use fake or unconsented addresses for real campaign sends.

## Offline send checks

Every Resend payload includes HTML plus plain text derived from that final HTML,
including CTA/footer links and image alt text. Images use base64 encoded inline
CID attachments. If an image is absent from the client cache manifest, the
existing bounded asset fetch/cache path prepares it before sending; legacy HTTP
sources remain supported through this path. Unsafe local/data/unmatched CID
sources fail before the provider call. The shared asset pipeline normalizes
supported raster images for mail client compatibility; SVG sources require a
raster replacement before sending.

Run `python manage.py test email_delivery.test_payloads email_delivery.tests`
for mocked provider checks. No API credentials or external calls are needed.

For a real MIME capture, start a local [Mailpit](https://github.com/axllent/mailpit)
with its default SMTP `127.0.0.1:1025` and HTTP `127.0.0.1:8025` ports, without
SMTP relay/forwarding. From `backend`, run in PowerShell:

```powershell
$env:YOKAI_MAILPIT_TEST='1'
python manage.py test email_delivery.test_mailpit
Remove-Item Env:YOKAI_MAILPIT_TEST
```

This test replaces only the Resend network transport with local SMTP, then reads
Mailpit's captured MIME and HTML compatibility checks. It checks the generated
text, links and embedded image bytes/CID association. It does not validate
Resend's own MIME encoding or actual Gmail/Outlook rendering. Link checking is
excluded because it would fetch fixture URLs. Mailpit remains a dev/test tool;
production sending continues through Resend. The test skips unless opted in.
