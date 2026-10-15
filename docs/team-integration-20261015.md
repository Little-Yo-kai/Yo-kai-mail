# Team branch integration — 15 October 2026

Integration starts from current `main` at `cf98fce`, retaining its campaign
gateway contracts, lifecycle protections, version history, and ownership checks.

| Work | Source head | Integrated path |
| --- | --- | --- |
| Email generation and section regeneration | `sabi` / `214a458` | Existing current-main port `67f47ce`, including its validation fixes |
| Website crawl and asset pipeline | `feat/website-intelligence-continued` / `53ae847` | Existing current-main port `aec4f80`, repaired and connected |
| Contacts, delivery, frontend | `contacts-delivery-resend` / `aa81b49` | Current-main port `49a8938`, plus omitted UI styling/navigation and API adaptation |
| Bounded visual critique/revision | `saransh` / `e053120` | Full branch merge, including Copilot PR #7, with campaign adapter |
| Phase 2 orchestration | `feat/phase2-*` | Already represented in current main; integration-contract branch has the same final tree |

The website source diverged 276 commits behind current main. Its old settings,
routes and dependency baseline are not substituted for the current ones. The
older email-generation integration is superseded by its current-main port.
Original teammate branches remain available.

## Integration repairs

- Scope asset promotion to the authenticated owner, matching read/list access.
- Keep deduplicated asset references valid when a shared temporary object is
  promoted and removed. Clear temporary expiry on persistent records.
- Connect visual revision to campaign versioning with the real persisted
  inventory and revision instruction. Failed critiques do not replace the
  saved design. Revised designs pass application contract validation.
- Supply JWT login/refresh routes and authentication for the contacts UI while
  preserving existing token/session clients.
- Use current `selection`, `audience_snapshot`, and `delivery_job` API contracts.
  Provide owner-scoped recipient activity and schedule cancellation under the
  delivery app, retaining the provider-independent campaign summary.
- Keep audience snapshot creation in the contacts domain and campaign mutation
  in campaign orchestration. Reject empty/malformed selections and count
  excluded recipients once.
- Freeze subject, HTML, design version and idempotency key on each delivery job;
  older jobs retain a rendering fallback. The new migration adds these fields.
- Preserve current lifecycle transitions rather than porting duplicate legacy
  campaign routes or a second send-job orchestrator.
- Guard robots.txt requests and redirects against private destinations, support
  Firecrawl metadata casing, and remove crawl debugging prints.
- Replace a hard-coded GitHub runner fixture path with a path relative to the
  test file; reconcile and lock dependencies and npm runtimes.
- Restrict row locks to their own model to support nullable related objects on
  PostgreSQL. Validate both databases in Actions.

## Validation scope

`campaigns/test_team_integration.py` exercises the actual authenticated APIs,
gateway adapters, persistence, renderer, revision loop, audience resolution,
worker, cancellation and signed webhook processing. Provider network calls,
browser/compiler subprocess edges and broker submission are mocked there.
`email_rendering/test_runtime.py` separately runs the real MJML compiler and
desktop/mobile Chromium screenshots in CI. No real campaign is sent by tests.

The Actions workflow runs on integration branches, pull requests and main.
Backend migration/schema/tests and frontend builds must all pass on the final
combined commit before merging.

Production credentials, a running broker/worker, durable publicly served HTTPS
assets, and a verified Resend sender remain deployment configuration. No
teammate editor branch was present to integrate; the existing campaign APIs
remain the editor's contract.
