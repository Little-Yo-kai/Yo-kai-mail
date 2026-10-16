"use client";

import { useEffect, useReducer, useRef } from "react";
import {
  emailEditorReducer,
  hasPendingEditorChanges,
  initialEditorState,
  readUploadedEmailAsset,
  type EditableEmailDesign,
  type EmailAsset,
} from "../lib/email-editor";

export type { EditableEmailDesign, EmailAsset } from "../lib/email-editor";

type Props = {
  apiBase: string;
  design: EditableEmailDesign;
  assets: EmailAsset[];
  onApply: (design: EditableEmailDesign, assets: EmailAsset[]) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
};

export function EmailImageEditor({
  apiBase,
  design,
  assets,
  onApply,
  onDirtyChange,
}: Props) {
  const [state, dispatch] = useReducer(emailEditorReducer, initialEditorState(design, assets));
  const { draft, inventory, dirty, error } = state;
  const busy = state.operation !== null;
  const sequence = useRef(0);
  const activeRequest = useRef<{ id: number; controller: AbortController } | null>(null);

  useEffect(() => {
    dispatch({ type: "reset", design, assets });
    return () => {
      activeRequest.current?.controller.abort();
      activeRequest.current = null;
    };
  }, [design, assets]);

  useEffect(() => {
    onDirtyChange(hasPendingEditorChanges(state));
  }, [state.dirty, state.operation, onDirtyChange]);

  function updateSection(
    id: string,
    changes: Partial<Pick<EditableEmailDesign["sections"][number], "headline" | "body" | "asset_ids" | "layout">>,
  ) {
    dispatch({ type: "section", id, changes });
  }

  async function uploadImage(id: string, file: File) {
    if (activeRequest.current) return;
    const request = { id: ++sequence.current, controller: new AbortController() };
    activeRequest.current = request;
    dispatch({ type: "begin", id: request.id, kind: "upload" });
    try {
      const body = new FormData();
      body.append("image", file);
      const response = await fetch(`${apiBase}/api/demo/images/`, {
        method: "POST",
        body,
        signal: request.controller.signal,
      });
      const asset = await readUploadedEmailAsset(response);
      if (activeRequest.current === request) {
        dispatch({ type: "uploaded", id: request.id, sectionId: id, asset });
      }
    } catch (uploadError) {
      if (activeRequest.current === request && !request.controller.signal.aborted) {
        dispatch({ type: "failed", id: request.id, error: uploadError instanceof Error ? uploadError.message : "Image upload failed." });
      }
    } finally {
      if (activeRequest.current === request) {
        activeRequest.current = null;
        dispatch({ type: "finished", id: request.id });
      }
    }
  }

  async function apply() {
    if (activeRequest.current) return;
    if (!draft.subject.trim() || !draft.preheader.trim()) {
      dispatch({ type: "error", error: "Add a subject and preview text before applying." });
      return;
    }
    const request = { id: ++sequence.current, controller: new AbortController() };
    activeRequest.current = request;
    dispatch({ type: "begin", id: request.id, kind: "apply" });
    try {
      await onApply(draft, inventory);
      if (activeRequest.current === request) dispatch({ type: "applied", id: request.id });
    } catch (applyError) {
      if (activeRequest.current === request) {
        dispatch({ type: "failed", id: request.id, error: applyError instanceof Error ? applyError.message : "Could not update the email." });
      }
    } finally {
      if (activeRequest.current === request) {
        activeRequest.current = null;
        dispatch({ type: "finished", id: request.id });
      }
    }
  }

  return (
    <details className="image-editor" open>
      <summary>
        <span>Copy, images & layout</span>
        <span className="editor-subtitle">Refine your email before sending</span>
      </summary>
      <p className="editor-help">
        Edit your copy, choose a website image or upload your own. Apply changes
        to update the preview and test email. Keep product claims accurate;
        buttons keep their original destination.
      </p>
      <form onSubmit={(event) => { event.preventDefault(); void apply(); }}>
      <div className="image-editor-section">
        <label>
          Subject
          <input aria-label="Email subject" value={draft.subject} maxLength={200} required disabled={busy}
            onChange={(event) => dispatch({ type: "copy", field: "subject", value: event.target.value })} />
        </label>
        <label>
          Preview text
          <input aria-label="Email preview text" value={draft.preheader} maxLength={240} required disabled={busy}
            onChange={(event) => dispatch({ type: "copy", field: "preheader", value: event.target.value })} />
        </label>
      </div>
      <div className="image-editor-grid">
        {draft.sections
          .filter(
            (section) =>
              !["divider", "footer", "product_grid"].includes(section.type),
          )
          .map((section, index) => (
            <div className="image-editor-section" key={section.id}>
              <div className="image-editor-heading">
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>
                  {section.headline || section.type.replaceAll("_", " ")}
                </strong>
              </div>
              <label>
                Headline
                <input aria-label={`Headline for ${section.id}`} value={section.headline ?? ""}
                  maxLength={160} required={section.type === "hero"} disabled={busy}
                  onChange={(event) => updateSection(section.id, { headline: event.target.value })} />
              </label>
              <label>
                Body copy
                <textarea aria-label={`Body copy for ${section.id}`} value={section.body ?? ""}
                  maxLength={1200} rows={4} disabled={busy}
                  onChange={(event) => updateSection(section.id, { body: event.target.value })} />
              </label>
              {section.cta && (
                <label>
                  Button label
                  <input aria-label={`Button label for ${section.id}`} value={section.cta.label}
                    maxLength={100} required disabled={busy}
                    onChange={(event) => dispatch({ type: "cta-label", id: section.id, value: event.target.value })} />
                </label>
              )}
              <label>
                Image
                <select
                  aria-label={`Image for ${section.id}`}
                  disabled={busy}
                  value={section.asset_ids[0] || ""}
                  onChange={(event) =>
                    updateSection(section.id, {
                      asset_ids: event.target.value ? [event.target.value] : [],
                    })
                  }
                >
                  <option value="">No image</option>
                  {inventory
                    .filter((asset) => asset.kind !== "logo")
                    .map((asset, i) => (
                      <option key={asset.asset_id} value={asset.asset_id}>
                        {asset.asset_id.startsWith("upload_")
                          ? "Uploaded image"
                          : `Website image ${i + 1}`}{" "}
                        · {asset.kind}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Placement
                <select
                  aria-label={`Image placement for ${section.id}`}
                  disabled={busy || !section.asset_ids.length}
                  value={section.layout}
                  onChange={(event) =>
                    updateSection(section.id, { layout: event.target.value })
                  }
                >
                  <option value="full_width">Full-width feature</option>
                  <option value="centered">Centered / above text</option>
                  <option value="split_image_left">Image on the left</option>
                  <option value="split_image_right">Image on the right</option>
                  {![
                    "full_width",
                    "centered",
                    "split_image_left",
                    "split_image_right",
                  ].includes(section.layout) && (
                    <option value={section.layout}>Original layout</option>
                  )}
                </select>
              </label>
              <label className="image-upload-button">
                Upload replacement
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  disabled={busy}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void uploadImage(section.id, file);
                    event.target.value = "";
                  }}
                />
              </label>
            </div>
          ))}
      </div>
      {error && (
        <p className="send-status error" role="alert">
          {error}
        </p>
      )}
      <div className="image-editor-actions">
        <span>
          {dirty
            ? "You have unapplied changes."
            : "Preview and test email use the applied design."}
        </span>
        <button type="submit" disabled={busy || !dirty}>
          {state.operation?.kind === "upload" ? "Uploading…" : busy ? "Applying…" : "Apply design changes"}
        </button>
      </div>
      </form>
    </details>
  );
}
