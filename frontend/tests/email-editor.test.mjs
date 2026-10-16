import assert from "node:assert/strict";
import { test } from "node:test";
import {
  emailEditorReducer,
  hasPendingEditorChanges,
  initialEditorState,
  readUploadedEmailAsset,
} from "../lib/email-editor.ts";

function fixture() {
  const design = {
    schema_version: "1.1",
    subject: "Meet Example",
    preheader: "Discover the collection.",
    theme: { content_width: "standard", button_color_role: "primary" },
    verified_campaign_data: { claim: "Approved product information" },
    sections: [
      {
        id: "hero", type: "hero", layout: "full_width", order: 1,
        headline: "A considered introduction", body: "Verified story.",
        asset_ids: ["hero-image"],
        cta: { label: "Discover", url: "https://example.com/product?source=email" },
        style: { alignment: "center", spacing: "balanced" },
      },
      {
        id: "story", type: "intro", layout: "centered", order: 2,
        headline: "The story", body: "More information.", asset_ids: ["story-image"],
      },
    ],
  };
  const assets = [
    { asset_id: "hero-image", kind: "hero", url: "https://example.com/hero.jpg" },
    { asset_id: "story-image", kind: "detail", url: "https://example.com/story.jpg" },
  ];
  return { design, assets, state: initialEditorState(design, assets) };
}

test("copy edits preserve destinations, theme, metadata and the applied design", () => {
  const { design, assets, state } = fixture();
  const original = structuredClone(design);
  let edited = emailEditorReducer(state, { type: "copy", field: "subject", value: "Hello {{ first_name }}" });
  edited = emailEditorReducer(edited, { type: "copy", field: "preheader", value: "A useful preview." });
  edited = emailEditorReducer(edited, { type: "section", id: "hero", changes: { headline: "A new headline", body: "Updated copy." } });
  edited = emailEditorReducer(edited, { type: "cta-label", id: "hero", value: "Explore" });
  assert.equal(edited.draft.subject, "Hello {{ first_name }}");
  assert.equal(edited.draft.preheader, "A useful preview.");
  assert.equal(edited.draft.sections[0].body, "Updated copy.");
  assert.equal(edited.draft.sections[0].cta.label, "Explore");
  assert.equal(edited.draft.sections[0].cta.url, original.sections[0].cta.url);
  assert.deepEqual(edited.draft.theme, original.theme);
  assert.deepEqual(edited.draft.verified_campaign_data, original.verified_campaign_data);
  assert.deepEqual(edited.draft.sections[1], original.sections[1]);
  assert.equal(edited.inventory, assets);
  assert.deepEqual(design, original);
  assert.equal(hasPendingEditorChanges(edited), true);
});

test("upload failure keeps existing edits and blocks sending until they are applied", () => {
  let { state } = fixture();
  state = emailEditorReducer(state, { type: "copy", field: "subject", value: "Edited subject" });
  state = emailEditorReducer(state, { type: "begin", id: 1, kind: "upload" });
  state = emailEditorReducer(state, { type: "failed", id: 1, error: "Upload failed" });
  state = emailEditorReducer(state, { type: "finished", id: 1 });
  assert.equal(state.draft.subject, "Edited subject");
  assert.equal(state.error, "Upload failed");
  assert.equal(state.operation, null);
  assert.equal(hasPendingEditorChanges(state), true);
});

test("failed upload on an unchanged draft releases the pending delivery guard", () => {
  let { state } = fixture();
  state = emailEditorReducer(state, { type: "begin", id: 1, kind: "upload" });
  assert.equal(hasPendingEditorChanges(state), true);
  state = emailEditorReducer(state, { type: "failed", id: 1, error: "Unsupported image" });
  assert.equal(hasPendingEditorChanges(state), false);
});

test("late upload responses cannot mutate a replacement design or its new request", () => {
  const { design, assets, state } = fixture();
  const uploading = emailEditorReducer(state, { type: "begin", id: 1, kind: "upload" });
  const replacement = emailEditorReducer(uploading, {
    type: "reset", design: { ...design, subject: "A replacement email" }, assets,
  });
  const current = emailEditorReducer(replacement, { type: "begin", id: 2, kind: "upload" });
  const lateAsset = { asset_id: "old-upload", kind: "product", url: "https://example.com/old.jpg" };
  for (const action of [
    { type: "uploaded", id: 1, sectionId: "hero", asset: lateAsset },
    { type: "failed", id: 1, error: "Old upload failed" },
    { type: "finished", id: 1 },
    { type: "applied", id: 1 },
  ]) {
    assert.equal(emailEditorReducer(current, action), current);
  }
  assert.equal(current.draft.subject, "A replacement email");
  assert.equal(current.operation.id, 2);
});

test("upload changes only the selected section, and failed apply retains that draft", () => {
  const { state, assets, design } = fixture();
  const uploaded = { asset_id: "upload-new", kind: "product", url: "http://localhost:8000/api/demo/images/new/" };
  let edited = emailEditorReducer(state, { type: "begin", id: 1, kind: "upload" });
  edited = emailEditorReducer(edited, { type: "uploaded", id: 1, sectionId: "hero", asset: uploaded });
  edited = emailEditorReducer(edited, { type: "finished", id: 1 });
  assert.deepEqual(edited.draft.sections[0].asset_ids, ["upload-new"]);
  assert.deepEqual(edited.draft.sections[1], design.sections[1]);
  assert.deepEqual(assets.map((asset) => asset.asset_id), ["hero-image", "story-image"]);
  assert.equal(edited.inventory.at(-1), uploaded);
  edited = emailEditorReducer(edited, { type: "begin", id: 2, kind: "apply" });
  edited = emailEditorReducer(edited, { type: "failed", id: 2, error: "Preview unavailable" });
  assert.equal(hasPendingEditorChanges(edited), true);
  assert.deepEqual(edited.draft.sections[0].asset_ids, ["upload-new"]);
  edited = emailEditorReducer(edited, { type: "begin", id: 3, kind: "apply" });
  edited = emailEditorReducer(edited, { type: "applied", id: 3 });
  assert.equal(hasPendingEditorChanges(edited), false);
});

test("upload errors explain validation and gateway failures without accepting bad assets", async () => {
  await assert.rejects(readUploadedEmailAsset(Response.json({ image: ["Image exceeds the upload limit."] }, { status: 400 })), /upload limit/);
  await assert.rejects(readUploadedEmailAsset(new Response("Gateway timeout", { status: 504 })), /HTTP 504/);
  await assert.rejects(readUploadedEmailAsset(Response.json({ success: true, data: {} })), /usable image/);
  await assert.rejects(readUploadedEmailAsset(Response.json({ success: true, data: { asset: { asset_id: "bad", url: {}, kind: "product" } } })), /usable image/);
  const asset = { asset_id: "upload-image", kind: "product", url: "https://example.com/image.jpg" };
  assert.deepEqual(await readUploadedEmailAsset(Response.json({ success: true, data: { asset } })), asset);
});
