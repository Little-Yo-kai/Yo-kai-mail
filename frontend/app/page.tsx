"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";

type DemoResponse = {
  success: boolean;
  stage?: string;
  error?: string;
  details?: string;
  data?: {
    mode: "uploaded_reference" | "automatic_reference";
    brand_profile: {
      identity?: {
        name?: string;
        industry?: string;
      };
    };
    reference: {
      source: string;
      name?: string;
      recipe_family?: string;
    };
    email_design: {
      subject: string;
      preheader: string;
      sections: Array<{ id: string; type: string }>;
    };
    asset_inventory: Array<{
      asset_id: string;
      kind: string;
      url: string;
    }>;
    render: {
      html: string;
      mjml: string;
      compiler_errors: unknown[];
      rendered_sections: number;
    };
  };
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

function slugify(value: string) {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "yo-kai-email"
  );
}

function downloadText(filename: string, value: string, type: string) {
  const blob = new Blob([value], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [reference, setReference] = useState<File | null>(null);
  const [instructions, setInstructions] = useState("");
  const [result, setResult] = useState<DemoResponse["data"] | null>(null);
  const [error, setError] = useState("");
  const [errorStage, setErrorStage] = useState("");
  const [loading, setLoading] = useState(false);
  const [viewport, setViewport] = useState<"desktop" | "mobile">("desktop");
  const [copied, setCopied] = useState(false);

  const brandName = result?.brand_profile.identity?.name || "Generated email";
  const fileBase = useMemo(() => slugify(brandName), [brandName]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setErrorStage("");
    setResult(null);
    setLoading(true);

    const body = new FormData();
    body.append("url", url.trim());
    if (reference) {
      body.append("reference_image", reference);
    }
    if (instructions.trim()) {
      body.append("additional_instructions", instructions.trim());
    }

    try {
      const response = await fetch(`${API_BASE}/api/demo/generate/`, {
        method: "POST",
        body,
      });

      const payload = (await response.json()) as DemoResponse;

      if (!response.ok || !payload.success || !payload.data) {
        setError(
          payload.error ||
            "The generation did not complete. Check the backend logs and try again.",
        );
        setErrorStage(payload.stage || "");
        return;
      }

      setResult(payload.data);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not reach the Yo-kai Mail backend.",
      );
    } finally {
      setLoading(false);
    }
  }

  function handleReference(event: ChangeEvent<HTMLInputElement>) {
    setReference(event.target.files?.[0] ?? null);
  }

  function openFullPreview() {
    if (!result) return;

    const blob = new Blob([result.render.html], { type: "text/html" });
    const previewUrl = URL.createObjectURL(blob);
    window.open(previewUrl, "_blank", "noopener,noreferrer");
    window.setTimeout(() => URL.revokeObjectURL(previewUrl), 60_000);
  }

  async function copyHtml() {
    if (!result) return;
    await navigator.clipboard.writeText(result.render.html);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <main>
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark">Y</div>
          <div>
            <strong>Yo-kai Mail</strong>
            <span>Phase 1 demo</span>
          </div>
        </div>
        <div className="status-pill">
          <span className="status-dot" />
          Generation engine online
        </div>
      </header>

      {!result ? (
        <section className="hero-shell">
          <div className="intro-copy">
            <p className="eyebrow">WEBSITE → EMAIL</p>
            <h1>Turn a website into a campaign-ready email.</h1>
            <p className="lede">
              Paste a public website. Yo-kai studies the brand, chooses a design
              direction, plans the campaign and renders a responsive email.
              Add a reference screenshot only when you want to guide the visual
              direction yourself.
            </p>

            <div className="pipeline">
              {[
                "Understand brand",
                "Choose direction",
                "Plan campaign",
                "Compose design",
                "Render HTML",
              ].map((step, index) => (
                <div className="pipeline-step" key={step}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  {step}
                </div>
              ))}
            </div>
          </div>

          <form className="generator-card" onSubmit={handleSubmit}>
            <div className="card-heading">
              <div>
                <p className="eyebrow">NEW GENERATION</p>
                <h2>Give Yo-kai a starting point.</h2>
              </div>
              <span className="required-note">URL is enough</span>
            </div>

            <label className="field">
              <span>Website URL</span>
              <input
                type="url"
                required
                placeholder="https://example.com"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                disabled={loading}
              />
            </label>

            <label className="upload-field">
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={handleReference}
                disabled={loading}
              />
              <div className="upload-icon">+</div>
              <div>
                <strong>
                  {reference ? reference.name : "Add a reference screenshot"}
                </strong>
                <span>
                  {reference
                    ? "Yo-kai will use this visual direction."
                    : "Optional · PNG, JPG or WebP"}
                </span>
              </div>
              {reference && (
                <button
                  type="button"
                  className="text-button"
                  onClick={(event) => {
                    event.preventDefault();
                    setReference(null);
                  }}
                >
                  Remove
                </button>
              )}
            </label>

            <label className="field">
              <span>
                Extra direction <em>optional</em>
              </span>
              <textarea
                rows={4}
                placeholder="e.g. Keep it minimal and premium. Focus on introducing the brand."
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
                disabled={loading}
              />
            </label>

            {error && (
              <div className="error-box">
                <strong>
                  {errorStage ? `Stopped at ${errorStage}` : "Generation failed"}
                </strong>
                <span>{error}</span>
              </div>
            )}

            <button className="primary-button" type="submit" disabled={loading}>
              {loading ? (
                <>
                  <span className="spinner" />
                  Building your email…
                </>
              ) : (
                <>
                  Generate email
                  <span aria-hidden="true">→</span>
                </>
              )}
            </button>

            {loading && (
              <div className="loading-copy">
                Yo-kai is running the complete generation pipeline. Brand
                analysis and AI composition can take a little while.
              </div>
            )}

            <p className="demo-note">
              Demo mode currently skips asset validation, visual critique and
              automatic revision. Those remain required before Phase 1 is
              considered complete.
            </p>
          </form>
        </section>
      ) : (
        <section className="result-shell">
          <div className="result-header">
            <div>
              <button
                className="back-button"
                type="button"
                onClick={() => {
                  setResult(null);
                  setError("");
                  setErrorStage("");
                }}
              >
                ← New generation
              </button>
              <p className="eyebrow">GENERATED EMAIL</p>
              <h1>{result.email_design.subject}</h1>
              <p className="preheader">{result.email_design.preheader}</p>
            </div>

            <div className="result-meta">
              <span>{brandName}</span>
              {result.brand_profile.identity?.industry && (
                <span>{result.brand_profile.identity.industry}</span>
              )}
              <span>
                {result.mode === "uploaded_reference"
                  ? "Uploaded reference"
                  : "Automatic reference"}
              </span>
            </div>
          </div>

          <div className="toolbar">
            <div className="viewport-toggle">
              <button
                type="button"
                className={viewport === "desktop" ? "active" : ""}
                onClick={() => setViewport("desktop")}
              >
                Desktop
              </button>
              <button
                type="button"
                className={viewport === "mobile" ? "active" : ""}
                onClick={() => setViewport("mobile")}
              >
                Mobile
              </button>
            </div>

            <div className="actions">
              <button type="button" onClick={openFullPreview}>
                Open full preview
              </button>
              <button
                type="button"
                onClick={() =>
                  downloadText(
                    `${fileBase}.html`,
                    result.render.html,
                    "text/html;charset=utf-8",
                  )
                }
              >
                Download HTML
              </button>
              <button type="button" onClick={copyHtml}>
                {copied ? "Copied" : "Copy HTML"}
              </button>
            </div>
          </div>

          <div className="preview-stage">
            <div
              className={`preview-frame ${viewport}`}
              aria-label="Generated email preview"
            >
              <iframe
                title="Generated email preview"
                srcDoc={result.render.html}
                sandbox="allow-popups allow-popups-to-escape-sandbox"
              />
            </div>
          </div>

          <div className="result-footer">
            <div className="summary-card">
              <span>Design direction</span>
              <strong>{result.reference.name || "Selected reference"}</strong>
              <p>
                {result.mode === "uploaded_reference"
                  ? "Built from the reference screenshot you supplied."
                  : "Selected automatically from Yo-kai's internal reference library."}
              </p>
            </div>

            <div className="summary-card">
              <span>Render</span>
              <strong>
                {result.render.rendered_sections} email sections
              </strong>
              <p>
                {result.render.compiler_errors.length === 0
                  ? "MJML compiled to responsive HTML without compiler errors."
                  : "The compiler returned warnings that should be reviewed."}
              </p>
            </div>

            <div className="summary-card">
              <span>Assets</span>
              <strong>{result.asset_inventory.length} discovered assets</strong>
              <p>
                External website assets are used as-is in this demo. Some sites
                may block hotlinking until the Phase 1 asset pipeline is added.
              </p>
            </div>

            <button
              className="secondary-button"
              type="button"
              onClick={() =>
                downloadText(
                  `${fileBase}.mjml`,
                  result.render.mjml,
                  "text/plain;charset=utf-8",
                )
              }
            >
              Download MJML source
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
