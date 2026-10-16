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
    body?: string | null;
    asset_ids: string[];
    cta?: { label: string; url?: string | null; [key: string]: unknown } | null;
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
};

export type EditorState = {
  draft: EditableEmailDesign;
  inventory: EmailAsset[];
  dirty: boolean;
  operation: { id: number; kind: "upload" | "apply" } | null;
  error: string;
};

type SectionChanges = Partial<Pick<
  EditableEmailDesign["sections"][number], "headline" | "body" | "asset_ids" | "layout"
>>;

type EditorAction =
  | { type: "reset"; design: EditableEmailDesign; assets: EmailAsset[] }
  | { type: "copy"; field: "subject" | "preheader"; value: string }
  | { type: "section"; id: string; changes: SectionChanges }
  | { type: "cta-label"; id: string; value: string }
  | { type: "begin"; id: number; kind: "upload" | "apply" }
  | { type: "uploaded"; id: number; sectionId: string; asset: EmailAsset }
  | { type: "applied"; id: number }
  | { type: "failed"; id: number; error: string }
  | { type: "finished"; id: number }
  | { type: "error"; error: string };

export function initialEditorState(design: EditableEmailDesign, assets: EmailAsset[]): EditorState {
  return { draft: design, inventory: assets, dirty: false, operation: null, error: "" };
}

export function hasPendingEditorChanges(state: EditorState) {
  return state.dirty || state.operation !== null;
}

export function emailEditorReducer(state: EditorState, action: EditorAction): EditorState {
  if (action.type === "reset") return initialEditorState(action.design, action.assets);
  if (action.type === "copy") {
    return { ...state, draft: { ...state.draft, [action.field]: action.value }, dirty: true, error: "" };
  }
  if (action.type === "section" || action.type === "cta-label") {
    if (!state.draft.sections.some((section) => section.id === action.id)) return state;
    return {
      ...state, dirty: true, error: "",
      draft: {
        ...state.draft,
        sections: state.draft.sections.map((section) => {
          if (section.id !== action.id) return section;
          if (action.type === "cta-label") {
            return section.cta ? { ...section, cta: { ...section.cta, label: action.value } } : section;
          }
          return { ...section, ...action.changes };
        }),
      },
    };
  }
  if (action.type === "error") return { ...state, error: action.error };
  if (action.type === "begin") return { ...state, operation: { id: action.id, kind: action.kind }, error: "" };
  // A response from a replaced design or an older request cannot change the
  // current draft, its inventory, or the guard used by test delivery.
  if (state.operation?.id !== action.id) return state;
  if (action.type === "uploaded") {
    return {
      ...state,
      dirty: true,
      inventory: [...state.inventory.filter((asset) => asset.asset_id !== action.asset.asset_id), action.asset],
      draft: {
        ...state.draft,
        sections: state.draft.sections.map((section) => section.id === action.sectionId
          ? { ...section, asset_ids: [action.asset.asset_id] } : section),
      },
    };
  }
  if (action.type === "applied") return { ...state, dirty: false, operation: null };
  if (action.type === "failed") return { ...state, operation: null, error: action.error };
  return { ...state, operation: null };
}

export async function readUploadedEmailAsset(response: Response): Promise<EmailAsset> {
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`Image upload returned HTTP ${response.status}. Please try again.`);
  }
  if (!response.ok || !payload?.success) {
    const error = payload?.error || payload?.image;
    throw new Error(typeof error === "string" ? error : Array.isArray(error) ? error.join(" ") : "Image upload failed.");
  }
  const asset = payload.data?.asset;
  if (!asset || ![asset.asset_id, asset.kind, asset.url].every((value) => typeof value === "string" && value.trim())) {
    throw new Error("The upload did not return a usable image. Please try again.");
  }
  return asset;
}
