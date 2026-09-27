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
  -> ready
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

This Sprint 0 skeleton does not yet implement:

- persistent AssetLibrary integration
- editor design-save endpoint
- campaign-level test-send endpoint
- audience resolution
- schedule/send job creation
- delivery summaries
- workspace/team ownership

Those are separate contract-driven checkpoints.


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
