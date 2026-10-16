# Yo-kai Mail

Email generation and campaign orchestration with a Django API and Next.js UI.
The application keeps `BrandProfile`, `ContentPlan`, `FactLedger`, and
`EmailDesign` as structured contracts. MJML renders the final HTML; the model
does not generate arbitrary email HTML.

## Start locally

From `backend/`:

```bash
uv sync --locked
cp .env.example .env
npm ci --prefix mjml_runtime
uv run playwright install chromium
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Configure Firecrawl and Gemini credentials in `backend/.env` for generation.
For actual email delivery, also configure Resend and a verified sender.

The generation page shows live stages and elapsed time, with a cancel button.
The default overall limit is four minutes (`DEMO_GENERATION_TIMEOUT_SECONDS`);
Firecrawl requests are limited to 40 seconds and each Gemini attempt to 60
seconds, clamped to the remaining generation time. Firecrawl's long automatic
resume and Gemini's hidden SDK retries are disabled. The shared Gemini fallback
handles 429/503 capacity errors with at most three attempts. It tries the primary,
configured fallback, then `GEMINI_ADDITIONAL_FALLBACK_MODELS` (default:
`gemini-3.5-flash-lite`), removing duplicates. With fewer than three distinct
models, the final model gets one short retry for 503. Authentication and schema
errors fail immediately. Preview image caching has
an eight-second budget and cannot discard a successfully compiled email.

Repeat generations reuse recent website, brand, reference, and campaign-plan
analysis while composing a fresh email. Uploaded references are analyzed alongside
the website. The result reports generation time; **Refresh website analysis**
bypasses reuse after a source change. See `backend/.env.example` for cache TTLs and
optional Redis sharing across workers. Cache failures fall back to fresh work.

`POST /api/demo/generate/` retains its JSON response. The page uses
`POST /api/demo/generate/stream/` for newline-delimited JSON events: `started`,
`progress`, `heartbeat`, then `result` or `error`. Streaming errors carry their
own `status`, `code`, `stage`, and `request_id` because HTTP headers have already
been sent. Logs include the request ID for failures and stage durations. Keep
proxy buffering disabled for this route and allow the configured generation
duration in server/proxy timeouts. Cancelled requests stop before the next stage;
an in-flight provider call finishes or times out before its worker slot is freed.

From `frontend/`, run `npm ci` and `npm run dev`. Open
<http://localhost:3000> for the generation demo or
<http://localhost:3000/contacts> for the authenticated contacts workspace.
`/contacts` uses the Django username and password with JWT access/refresh tokens;
existing dj-rest-auth token clients remain supported.

For campaign jobs, start Redis and run this in `backend/`:

```bash
uv run celery -A core worker --pool=solo --loglevel=info
```

Campaign delivery is explicitly enabled with `RESEND_CAMPAIGN_SEND_ENABLED=True`.
Images must be promoted to persistent storage served from an externally
reachable HTTPS origin. The included filesystem adapter is for local development;
deployments must arrange durable storage and HTTPS media serving.

## Campaign flow

Create a campaign, generate its design, optionally revise it, promote selected
assets, send a test, mark it ready, resolve an eligible audience, then send or
schedule. The worker sends the frozen approved subject/HTML. Signed Resend
webhooks update recipient activity. Contacts are checked again before sending
so later unsubscribes and suppressions are respected.

The current frontend includes the generation demo and contacts/delivery
workspace. Campaign APIs are documented at `/api/docs/swagger/`; a complete
visual campaign editor remains a separate feature.

## Validation

GitHub Actions validates backend checks, migrations, OpenAPI, and regression
tests on SQLite and PostgreSQL, plus the frontend production build. It also
executes the real MJML compiler and desktop/mobile screenshot smoke checks.
Frontend `npm test` covers streamed responses, provider failures, interrupted
connections, gateway errors, and upload validation messages.

Local checks from `backend/`:

```bash
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py spectacular --validate --fail-on-warn --file /tmp/yokai-schema.yml
uv run python manage.py test
EMAIL_RUNTIME_SMOKE=1 EMAIL_BROWSER_SMOKE=1 uv run python manage.py test email_rendering.test_runtime
```

`EMAIL_SCREENSHOT_EXECUTABLE_PATH` can select an installed Chrome/Chromium
binary instead of Playwright's downloaded browser. `DATABASE_URL` selects
PostgreSQL; omitting it retains SQLite.

See [integration notes](docs/team-integration-20261015.md),
[campaign contracts](backend/campaigns/README.md), and
[contacts/delivery](backend/email_delivery/README.md).
