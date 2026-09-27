# Campaign Orchestration Contract

This document defines the Phase 2 campaign boundary owned by integration/orchestration.

Other subsystems should depend on these campaign-level contracts rather than
manually chaining Yo-kai's internal debugging endpoints.

## Persistence model

### Campaign

A Campaign is the long-lived product record for one marketing workflow.

Core fields:

- `id` — UUID campaign identifier
- `owner` — authenticated Django user that owns the campaign
- `title`
- `status`
- `source_url`
- `reference_mode` — `automatic` or `uploaded`
- `additional_instructions`
- persisted structured generation outputs:
  - `campaign_brief`
  - `brand_profile`
  - `reference`
  - `content_plan`
- `active_design` — current CampaignDesignVersion
- `audience_selection` — temporary boundary for Friend 5's audience work
- `audience_snapshot_id` — future immutable resolved audience reference
- `send_mode`
- `scheduled_for`
- lifecycle timestamps

### CampaignDesignVersion

Structured EmailDesign versions are stored separately from Campaign so edits,
AI revisions, and regeneration do not overwrite history.

Fields:

- `id`
- `campaign`
- `version` — monotonically increasing within a campaign
- `source` — generated / user_edit / revision
- `email_design`
- `created_by`
- `created_at`

Only the structured EmailDesign is versioned here. Production delivery HTML
continues to come from the deterministic renderer.

## Lifecycle

Current state graph:

```text
draft
  -> generated

generated
  -> reviewed
  -> failed

reviewed
  -> test_sent
  -> generated
  -> failed

test_sent
  -> ready
  -> generated
  -> failed

ready
  -> scheduled
  -> sending
  -> generated
  -> failed

scheduled
  -> sending
  -> ready
  -> failed

sending
  -> sent
  -> failed

failed
  -> generated
  -> ready
```

`sent` is terminal in the current contract.

Generated/review/test/ready states require an active persisted EmailDesign.
Additional delivery-specific preconditions will be added when Friend 5's
AudienceSnapshot/DeliveryRecord contracts land.

## API

### Create campaign

`POST /api/campaigns/`

Requires authentication.

Example:

```json
{
  "title": "Autumn launch",
  "source_url": "https://example.com",
  "reference_mode": "automatic",
  "additional_instructions": "Keep it minimal."
}
```

Returns the persisted Campaign in `draft`.

### List current user's campaigns

`GET /api/campaigns/`

Only campaigns owned by the authenticated user are returned.

### Reopen campaign

`GET /api/campaigns/{campaign_id}/`

A user cannot read another user's campaign.

### Update campaign

`PATCH /api/campaigns/{campaign_id}/`

Draft generation inputs can be edited while status is `draft`.

Current mutable integration fields also include audience/send placeholders.
Status cannot be patched directly.

### Generate campaign

`POST /api/campaigns/{campaign_id}/generate/`

Multipart request.

Optional field:

- `reference_image`

When `reference_mode=uploaded`, a reference image is required.

This endpoint calls the existing Phase 1 generation pipeline, then persists:

- CampaignBrief
- BrandProfile
- selected/analyzed reference metadata
- ContentPlan
- a new CampaignDesignVersion containing EmailDesign

The new design becomes `active_design`, and the campaign moves to
`generated`.

Regeneration creates a new design version rather than overwriting history.

### Transition campaign

`POST /api/campaigns/{campaign_id}/transition/`

Example:

```json
{
  "status": "reviewed"
}
```

Only explicitly allowed state transitions succeed. Invalid transitions return
HTTP 409.

## Ownership and permissions

Campaign-level endpoints require authentication.

All reads and writes scope queries to:

```text
owner = request.user
```

This is the current single-user ownership boundary. A future workspace/team
model can replace or extend it without changing campaign IDs.

## Teammate handoffs

Friend 1 — Asset Pipeline:
- attach persistent AssetRecord references to campaign outputs without changing
  EmailDesign's asset-ID semantics
- campaign_id is the persistence context for asset promotion

Friend 2 — AI/Quality:
- create revised design versions with source=`revision`
- never overwrite the previous valid version

Friend 3 — Email Generation:
- generation/regeneration returns validated EmailDesign
- section regeneration should eventually create a new design version

Friend 4 — Editor:
- load `active_design.email_design`
- save user edits as a new version with source=`user_edit`
- do not edit compiled HTML as campaign state

Friend 5 — Contacts/Delivery:
- replace the temporary audience placeholders with AudienceSnapshot references
- delivery jobs and provider events should reference `campaign_id`

## Intentionally incomplete in this checkpoint

The campaign foundation intentionally does not own teammate subsystem
implementations. Current remaining implementation dependencies are:

- Friend 1's persistent AssetRecord/storage implementation
- Friend 2's AI revision implementation
- Friend 5's AudienceSnapshot/contact resolution implementation
- Friend 5's DeliveryJob/DeliveryRecord/provider-webhook implementation
- workspace/team ownership

Editor design-save and campaign-level test-send are already implemented.
The interfaces below define how the remaining teammate modules connect.


## Phase 2 workflow additions

### Persisted generation context

Campaign generation now persists the additional internal context needed to
continue the workflow after a restart:

- `fact_ledger`
- `asset_inventory`

The renderer therefore does not require the frontend to resend these contracts.

### Save active design version

`PUT /api/campaigns/{campaign_id}/design/`

Request:

```json
{
  "email_design": {
    "...": "current EmailDesign v1 contract"
  }
}
```

The submitted design is schema-validated before it is stored.

A successful save:

- creates a new `CampaignDesignVersion`
- marks its source as `user_edit`
- makes it the campaign's `active_design`
- preserves previous design versions
- returns the campaign to `generated` if it had already been reviewed,
  test-sent or marked ready
- clears stale review/test-ready timestamps

This is the endpoint Friend 4's editor/autosave layer should call. The editor
must never store raw MJML or raw HTML as campaign state.

### Render active campaign design

`GET /api/campaigns/{campaign_id}/render/`

The backend loads:

```text
Campaign.brand_profile
+ Campaign.active_design.email_design
+ Campaign.asset_inventory
        ↓
deterministic MJML renderer
        ↓
MJML compiler
        ↓
HTML
```

This keeps rendering inputs server-owned and prevents the frontend from
manually chaining internal contracts.

The response currently includes:

- `html`
- `mjml`
- compiler diagnostics
- resolved theme
- rendered section count
- available asset IDs

Friend 4 can use this route for campaign preview until a narrower preview
response is agreed.

### Send campaign test

`POST /api/campaigns/{campaign_id}/send-test/`

Request:

```json
{
  "to": "recipient@example.com"
}
```

Optional:

- `idempotency_key`

The endpoint:

1. loads the active persisted design
2. renders it through the deterministic renderer
3. compiles the exact campaign HTML
4. sends one recipient through the existing Resend test-delivery boundary
5. records lifecycle state/timestamps

State behavior:

```text
generated
   ↓
reviewed
   ↓
test_sent
```

A successful repeat test while already `test_sent` refreshes the test-send
timestamp. A test sent while `ready` does not invalidate readiness when the
design itself has not changed.

Provider-specific delivery records remain Friend 5's ownership. This endpoint
is an orchestration boundary, not the final bulk-send implementation.

### Current integration acceptance path

The integration test for this checkpoint exercises:

```text
persisted generated campaign
        ↓
real deterministic renderer
        ↓
mocked MJML compiler subprocess
        ↓
mocked Resend provider boundary
        ↓
test_sent
        ↓
ready
```

Only the external/runtime edges are mocked; campaign persistence, renderer
input assembly, state transitions and API boundaries are real.


## Phase 2 integration contracts

The campaign app owns orchestration. Teammate modules own their domain
implementation.

The stable Python boundary is defined in:

`campaigns/contracts.py`

The campaign-side orchestration is defined in:

`campaigns/integration_services.py`

No integration service imports a teammate's future Django model. Instead it
accepts a gateway that satisfies the documented Protocol.

### Friend 1 — AssetPromotionGateway

Input:

```text
campaign_id
+ only AssetDescriptors referenced by active EmailDesign
```

Output:

```text
AssetPromotionResult
  assets[]
    asset_id
    asset_record_id
    kind
    public_url
  unresolved_asset_ids[]
```

Campaign requirements:

- every asset referenced by the active EmailDesign must resolve
- returned asset IDs must match required asset IDs exactly
- asset kind may not change during promotion
- final URL must be public HTTP(S)
- promoted URLs are written back into Campaign.asset_inventory
- promoted descriptors use source=`asset_library`

The gateway implementation may use R2/S3/CDN or another storage provider.
Campaign orchestration does not need to know which provider is used.

### Friend 2 — DesignRevisionGateway

Input:

```text
campaign_id
BrandProfile
CampaignBrief
Reference
ContentPlan
FactLedger
current EmailDesign
revision instruction
```

Output:

```text
DesignRevisionResult
  email_design
  revision_notes[]
```

Campaign orchestration validates the returned EmailDesign, creates a new
CampaignDesignVersion with source=`revision`, makes it active, and invalidates
stale review/test-ready state.

The AI subsystem must never mutate Campaign or CampaignDesignVersion directly.

### Friend 5 — AudienceGateway

Input:

```text
campaign_id
owner_id
audience selection object
```

Output:

```text
AudienceSnapshotContract
  snapshot_id
  recipient_count
  excluded_count
  normalized selection
```

The snapshot is immutable from the campaign's perspective. Campaign stores
only the snapshot UUID and normalized selection; contact membership remains
owned by the contacts/delivery subsystem.

Current orchestration resolves an audience only after Campaign is `ready` and
rejects an empty deliverable snapshot.

### Friend 5 — DeliveryGateway

Create-delivery input:

```text
campaign_id
audience_snapshot_id
subject
final rendered HTML
mode = send_now | scheduled
scheduled_for
idempotency_key
```

Output:

```text
DeliveryJobContract
  job_id
  mode
  status
  scheduled_for
```

Campaign state mapping:

```text
ready + send_now
    -> DeliveryGateway
    -> sending

ready + scheduled
    -> DeliveryGateway
    -> scheduled
```

The delivery subsystem owns recipient expansion, batching, Resend calls,
DeliveryRecord persistence and webhook processing.

### Delivery summary

The delivery subsystem exposes a provider-independent summary:

```text
total
queued
sent
delivered
bounced
complained
failed
last_event_at
```

Campaign orchestration does not depend on Resend webhook payload shapes.

### Why gateways instead of direct imports?

This avoids coupling such as:

```python
from contacts.models import SomeModelFriend5HasNotFinishedYet
```

or:

```python
from assets.models import AssetRecord
```

inside campaign orchestration.

Instead:

```text
teammate implementation
        ↓
implements gateway contract
        ↓
campaign integration service
```

This lets each subsystem evolve internally while keeping the campaign workflow
stable.

### Contract-level orchestration already implemented

The campaign layer can now:

- identify only assets actually referenced by active EmailDesign
- promote those assets through an AssetPromotionGateway
- persist stable delivery URLs
- request an AI revision through a DesignRevisionGateway
- create a revision design version without overwriting history
- resolve and persist an immutable audience snapshot reference
- create immediate or scheduled delivery through a DeliveryGateway
- move campaign state to `sending` or `scheduled`
- request a provider-independent campaign delivery summary

The campaign API now exposes these orchestration routes, but each teammate
boundary is opt-in. If its configured gateway is absent, the endpoint returns
HTTP 503 rather than fabricating placeholder data.

Configuration is by import path:

```text
CAMPAIGN_ASSET_PROMOTION_GATEWAY
CAMPAIGN_DESIGN_REVISION_GATEWAY
CAMPAIGN_AUDIENCE_GATEWAY
CAMPAIGN_DELIVERY_GATEWAY
```

The values stay blank until the teammate-owned adapter exists.

### Campaign integration API

```text
POST /api/campaigns/{id}/assets/promote/
POST /api/campaigns/{id}/revision/
POST /api/campaigns/{id}/audience/resolve/
POST /api/campaigns/{id}/send/
POST /api/campaigns/{id}/schedule/
GET  /api/campaigns/{id}/delivery-summary/
```

Every route requires authentication and resolves the campaign through
`owner=request.user`.

The generic transition endpoint is intentionally restricted to human workflow
states (`reviewed` and `ready`). Users cannot PATCH or transition a campaign
directly into delivery-owned states such as `scheduled`, `sending`,
`sent`, or `failed`.

A campaign cannot become `ready` until a successful test send has been
recorded.

### Delivery safety invariants

Final campaign delivery requires:

1. an active EmailDesign
2. a successful test send before `ready`
3. an immutable audience snapshot
4. every image referenced by the active design to be promoted to a stable
   public HTTP(S) asset URL
5. an explicit immediate or scheduled send mode

The campaign layer derives a deterministic idempotency key from campaign,
active design, audience snapshot, send mode and scheduled time when the caller
does not provide one. This makes duplicate orchestration requests safe for a
delivery gateway that honors the key.

Asset promotion persists both the stable URL and the teammate-owned
`asset_record_id` in campaign asset inventory metadata while preserving
EmailDesign's existing asset-ID semantics.

### Delivery lifecycle callback

Friend 5 does not mutate Campaign directly. After a delivery worker/webhook
changes job state, it can call the campaign orchestration service with a
`DeliveryStateUpdateContract`:

```text
scheduled -> sending -> sent

scheduled -> failed
sending   -> failed
```

Impossible transitions are rejected.

### Provider failure classification

Gateway adapters may raise `CampaignGatewayExecutionError` with:

- a safe message
- `retryable`
- optional upstream `status_code`

The campaign API maps rate limiting to HTTP 429, retryable provider outages to
HTTP 503, and other upstream execution failures to HTTP 502. Contract/state
violations remain HTTP 409.

### Transaction and concurrency behavior

External website/AI generation is no longer held inside one long database
transaction. The expensive external generation work completes first, then the
campaign row is locked only for atomic persistence.

Campaign design version allocation also locks the campaign row before
computing the next version number, preventing concurrent edits from allocating
the same version.

### Contract test boundary

`campaigns/test_integrations.py` uses fake gateway objects only at teammate
boundaries. Campaign models, EmailDesign validation, versioning, state
transitions and persistence remain real.

This is the expected pattern for future integration tests: fake external/domain
edges, not the campaign orchestration itself.
