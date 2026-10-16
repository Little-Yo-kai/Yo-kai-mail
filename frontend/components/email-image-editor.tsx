"use client";

import { useEffect, useState } from "react";

export type EmailAsset = {
  asset_id: string;
  kind: string;
  url: string;
  source?: string;
};

export type EditableEmailDesign = {
  subject: string;
  preheader: string;
  theme: Record<string, string>;
  sections: Array<{
    id: string;
    type: string;
    layout: string;
    headline?: string | null;
    asset_ids: string[];
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
};

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
  const [draft, setDraft] = useState(design);
  const [inventory, setInventory] = useState(assets);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(design);
    setInventory(assets);
    setDirty(false);
    onDirtyChange(false);
  }, [design, assets, onDirtyChange]);

  function updateSection(
    id: string,
    changes: Partial<EditableEmailDesign["sections"][number]>,
  ) {
    setDraft((current) => ({
      ...current,
      sections: current.sections.map((section) =>
        section.id === id ? { ...section, ...changes } : section,
      ),
    }));
    setDirty(true);
    onDirtyChange(true);
  }

  async function uploadImage(id: string, file: File) {
    setBusy(true);
    onDirtyChange(true);
    setError("");
    try {
      const body = new FormData();
      body.append("image", file);
      const response = await fetch(`${apiBase}/api/demo/images/`, {
        method: "POST",
        body,
      });
      const payload = await response.json();
      if (!response.ok || !payload.success)
        throw new Error(
          payload.error || payload.image?.[0] || "Image upload failed.",
        );
      const asset = payload.data.asset as EmailAsset;
      setInventory((current) => [
        ...current.filter((item) => item.asset_id !== asset.asset_id),
        asset,
      ]);
      updateSection(id, { asset_ids: [asset.asset_id] });
    } catch (uploadError) {
      onDirtyChange(dirty);
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : "Image upload failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    setBusy(true);
    setError("");
    try {
      await onApply(draft, inventory);
    } catch (applyError) {
      setError(
        applyError instanceof Error
          ? applyError.message
          : "Could not update the email.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="image-editor" open>
      <summary>
        <span>Images & layout</span>
        <span className="editor-subtitle">Change a photo or its placement</span>
      </summary>
      <p className="editor-help">
        Choose a website image or upload your own. Apply changes to update the
        preview and test email.
      </p>
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
            : "Preview and test email use the same images."}
        </span>
        <button type="button" disabled={busy || !dirty} onClick={apply}>
          {busy ? "Updating…" : "Apply design changes"}
        </button>
      </div>
    </details>
  );
}
