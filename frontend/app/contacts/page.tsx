"use client";

import Link from "next/link";
import {
  ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const ACCESS_TOKEN_KEY = "yo-kai-access-token";
const REFRESH_TOKEN_KEY = "yo-kai-refresh-token";

type ApiEnvelope<T> = {
  success: boolean;
  data?: T;
  error?: string;
  detail?: string;
};

type Contact = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  display_name: string;
  status: string;
  consent_status: string;
  consented_at: string | null;
  consent_source: string;
  source: string;
};

type ContactList = {
  id: string;
  name: string;
  description: string;
  member_count: number;
};

type Campaign = {
  id: string;
  title: string;
  status: string;
  source_url: string;
  scheduled_for: string | null;
  audience_snapshot_id: string | null;
  active_design: { id: string; version: number } | null;
};

type ImportSummary = {
  accepted: number;
  duplicate: number;
  invalid: number;
  skipped: number;
  row_errors: Array<{ row: number; reason: string }>;
};

type AudienceResult = {
  snapshot_id: string;
  recipient_count: number;
  excluded_count: number;
};

type AudienceResponse = { campaign: Campaign; audience_snapshot: AudienceResult };
type DeliveryResponse = {
  campaign: Campaign;
  delivery_job: { job_id: string; status: string; scheduled_for: string | null };
};

type RecipientRecord = {
  id: string;
  recipient_email: string;
  provider: string;
  provider_message_id: string | null;
  status: string;
  last_event_type: string;
  last_event_at: string | null;
  sent_at: string | null;
  failure_reason: string;
};

type DeliverySummary = {
  campaign_id: string;
  campaign_status: string;
  job: {
    id: string;
    status: string;
    scheduled_for: string | null;
    started_at: string | null;
    completed_at: string | null;
    error_summary: string;
  } | null;
  counts: {
    queued: number;
    sent: number;
    delivered: number;
    bounced: number;
    failed: number;
    complained: number;
    suppressed: number;
  };
  recipients: {
    total: number;
    limit: number;
    offset: number;
    items: RecipientRecord[];
  };
};

function unwrap<T>(envelope: ApiEnvelope<T>): T {
  if (!envelope.success || envelope.data === undefined) {
    throw new Error(envelope.error || envelope.detail || "The request failed.");
  }
  return envelope.data;
}

async function responseError(response: Response) {
  const payload = (await response.json().catch(() => null)) as
    | Record<string, unknown>
    | null;
  if (payload) {
    const message = payload.error ?? payload.detail;
    if (typeof message === "string") return message;
    const firstFieldError = Object.values(payload).flat(Infinity)[0];
    if (typeof firstFieldError === "string") return firstFieldError;
  }
  return `The request failed (${response.status}).`;
}

function formatDate(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function localDateTimeMinimum() {
  const date = new Date(Date.now() + 5 * 60 * 1000);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function downloadContactTemplate() {
  const content =
    "email,first_name,last_name,display_name,consent_status,consented_at,consent_source,source\n";
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/csv;charset=utf-8" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "yo-kai-contacts-template.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

function statusLabel(value: string) {
  return value.replaceAll("_", " ");
}

export default function ContactsPage() {
  const [hydrated, setHydrated] = useState(false);
  const [accessToken, setAccessToken] = useState("");
  const [refreshToken, setRefreshToken] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [signingIn, setSigningIn] = useState(false);
  const [loginError, setLoginError] = useState("");
  const [pageError, setPageError] = useState("");
  const [notice, setNotice] = useState("");
  const [activePanel, setActivePanel] = useState<"contacts" | "delivery">(
    "contacts",
  );
  const [loading, setLoading] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contactLists, setContactLists] = useState<ContactList[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [listFilter, setListFilter] = useState("");
  const [search, setSearch] = useState("");
  const [selectedContactIds, setSelectedContactIds] = useState<string[]>([]);
  const [membershipListId, setMembershipListId] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [importSummary, setImportSummary] = useState<ImportSummary | null>(null);
  const [importing, setImporting] = useState(false);
  const [listName, setListName] = useState("");
  const [listDescription, setListDescription] = useState("");
  const [creatingList, setCreatingList] = useState(false);
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [audienceListIds, setAudienceListIds] = useState<string[]>([]);
  const [audienceResult, setAudienceResult] = useState<AudienceResult | null>(
    null,
  );
  const [resolvedCampaignId, setResolvedCampaignId] = useState("");
  const [resolvingAudience, setResolvingAudience] = useState(false);
  const [sending, setSending] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [scheduledFor, setScheduledFor] = useState("");
  const [summary, setSummary] = useState<DeliverySummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const clearAuth = useCallback(() => {
    sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    sessionStorage.removeItem(REFRESH_TOKEN_KEY);
    setAccessToken("");
    setRefreshToken("");
    setContacts([]);
    setContactLists([]);
    setCampaigns([]);
    setSummary(null);
    setAudienceResult(null);
  }, []);

  const apiRequest = useCallback(
    async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
      const perform = (token: string) => {
        const headers = new Headers(init.headers);
        headers.set("Authorization", `Bearer ${token}`);
        if (init.body && !(init.body instanceof FormData)) {
          headers.set("Content-Type", "application/json");
        }
        return fetch(`${API_BASE}${path}`, { ...init, headers });
      };

      let response = await perform(accessToken);
      if (response.status === 401 && refreshToken) {
        const refreshResponse = await fetch(`${API_BASE}/api/auth/token/refresh/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh: refreshToken }),
        });
        if (refreshResponse.ok) {
          const refreshed = (await refreshResponse.json()) as {
            access: string;
            refresh?: string;
          };
          sessionStorage.setItem(ACCESS_TOKEN_KEY, refreshed.access);
          setAccessToken(refreshed.access);
          if (refreshed.refresh) {
            sessionStorage.setItem(REFRESH_TOKEN_KEY, refreshed.refresh);
            setRefreshToken(refreshed.refresh);
          }
          response = await perform(refreshed.access);
        } else {
          clearAuth();
          throw new Error("Your session expired. Sign in again to continue.");
        }
      }

      if (!response.ok) throw new Error(await responseError(response));
      return (await response.json()) as T;
    },
    [accessToken, clearAuth, refreshToken],
  );

  const loadResources = useCallback(async () => {
    setLoading(true);
    setPageError("");
    const contactsPath = listFilter
      ? `/api/email-delivery/contacts/?list_id=${encodeURIComponent(listFilter)}`
      : "/api/email-delivery/contacts/";
    try {
      const [contactEnvelope, listEnvelope, campaignEnvelope] =
        await Promise.all([
          apiRequest<ApiEnvelope<Contact[]>>(contactsPath),
          apiRequest<ApiEnvelope<ContactList[]>>("/api/email-delivery/contact-lists/"),
          apiRequest<ApiEnvelope<Campaign[]>>("/api/campaigns/"),
        ]);
      const nextContacts = unwrap(contactEnvelope);
      const nextLists = unwrap(listEnvelope);
      const nextCampaigns = unwrap(campaignEnvelope);
      setContacts(nextContacts);
      setContactLists(nextLists);
      setCampaigns(nextCampaigns);
      setSelectedCampaignId((current) =>
        nextCampaigns.some((campaign) => campaign.id === current)
          ? current
          : (nextCampaigns[0]?.id ?? ""),
      );
      setSelectedContactIds((current) =>
        current.filter((id) => nextContacts.some((contact) => contact.id === id)),
      );
    } catch (error) {
      setPageError(
        error instanceof Error ? error.message : "Could not load your workspace.",
      );
    } finally {
      setLoading(false);
    }
  }, [apiRequest, listFilter]);

  const loadSummary = useCallback(
    async (offset = 0, campaignId = selectedCampaignId) => {
      if (!campaignId) {
        setSummary(null);
        return;
      }
      setSummaryLoading(true);
      try {
        const envelope = await apiRequest<ApiEnvelope<DeliverySummary>>(
          `/api/email-delivery/campaigns/${campaignId}/activity/?limit=50&offset=${offset}`,
        );
        setSummary(unwrap(envelope));
      } catch (error) {
        setSummary(null);
        setPageError(
          error instanceof Error
            ? error.message
            : "Could not load campaign delivery activity.",
        );
      } finally {
        setSummaryLoading(false);
      }
    },
    [apiRequest, selectedCampaignId],
  );

  useEffect(() => {
    setAccessToken(sessionStorage.getItem(ACCESS_TOKEN_KEY) ?? "");
    setRefreshToken(sessionStorage.getItem(REFRESH_TOKEN_KEY) ?? "");
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (accessToken) void loadResources();
  }, [accessToken, loadResources]);

  useEffect(() => {
    if (accessToken && selectedCampaignId) {
      void loadSummary(0, selectedCampaignId);
    } else {
      setSummary(null);
    }
  }, [accessToken, loadSummary, selectedCampaignId]);

  const visibleContacts = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    if (!query) return contacts;
    return contacts.filter((contact) =>
      [contact.email, contact.display_name, contact.first_name, contact.last_name]
        .join(" ")
        .toLocaleLowerCase()
        .includes(query),
    );
  }, [contacts, search]);

  const selectedCampaign = campaigns.find(
    (campaign) => campaign.id === selectedCampaignId,
  );
  const audienceIsCurrent =
    Boolean(audienceResult) && resolvedCampaignId === selectedCampaignId;
  const canResolveAudience = Boolean(
    selectedCampaign &&
      selectedCampaign.status === "ready",
  );

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSigningIn(true);
    setLoginError("");
    try {
      const response = await fetch(`${API_BASE}/api/auth/token/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const tokens = (await response.json()) as {
        access: string;
        refresh: string;
      };
      sessionStorage.setItem(ACCESS_TOKEN_KEY, tokens.access);
      sessionStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh);
      setAccessToken(tokens.access);
      setRefreshToken(tokens.refresh);
      setPassword("");
    } catch (error) {
      setLoginError(
        error instanceof Error
          ? error.message
          : "Sign-in failed. Check the account details and try again.",
      );
    } finally {
      setSigningIn(false);
    }
  }

  function handleCsvFile(event: ChangeEvent<HTMLInputElement>) {
    setCsvFile(event.target.files?.[0] ?? null);
    setImportSummary(null);
  }

  async function importCsv(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!csvFile) return;
    const form = event.currentTarget;
    setImporting(true);
    setPageError("");
    setNotice("");
    const body = new FormData();
    body.append("file", csvFile);
    if (listFilter) body.append("list_id", listFilter);
    try {
      const envelope = await apiRequest<ApiEnvelope<ImportSummary>>(
        "/api/email-delivery/contacts/import/",
        { method: "POST", body },
      );
      setImportSummary(unwrap(envelope));
      setNotice("Import finished. Existing contacts were deduplicated.");
      setCsvFile(null);
      form.reset();
      await loadResources();
    } catch (error) {
      setPageError(
        error instanceof Error ? error.message : "The CSV could not be imported.",
      );
    } finally {
      setImporting(false);
    }
  }

  async function createContactList(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreatingList(true);
    setPageError("");
    try {
      await apiRequest<ApiEnvelope<ContactList>>("/api/email-delivery/contact-lists/", {
        method: "POST",
        body: JSON.stringify({
          name: listName.trim(),
          description: listDescription.trim(),
        }),
      });
      setListName("");
      setListDescription("");
      setNotice("Contact list created.");
      await loadResources();
    } catch (error) {
      setPageError(
        error instanceof Error ? error.message : "The contact list could not be created.",
      );
    } finally {
      setCreatingList(false);
    }
  }

  async function addSelectedContacts() {
    if (!membershipListId || selectedContactIds.length === 0) return;
    setPageError("");
    try {
      const envelope = await apiRequest<
        ApiEnvelope<{ added: number; member_count: number }>
      >(`/api/email-delivery/contact-lists/${membershipListId}/members/`, {
        method: "POST",
        body: JSON.stringify({ contact_ids: selectedContactIds }),
      });
      const result = unwrap(envelope);
      setNotice(`${result.added} contact${result.added === 1 ? "" : "s"} added to the list.`);
      setSelectedContactIds([]);
      await loadResources();
    } catch (error) {
      setPageError(
        error instanceof Error ? error.message : "The selected contacts could not be added.",
      );
    }
  }

  async function unsubscribeContact(contact: Contact) {
    setPageError("");
    try {
      const envelope = await apiRequest<ApiEnvelope<Contact>>(
        `/api/email-delivery/contacts/${contact.id}/`,
        { method: "PATCH", body: JSON.stringify({ status: "unsubscribed" }) },
      );
      const updated = unwrap(envelope);
      setContacts((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice(`${contact.email} is unsubscribed and excluded from new sends.`);
    } catch (error) {
      setPageError(
        error instanceof Error ? error.message : "The contact status could not be updated.",
      );
    }
  }

  async function resolveAudience() {
    if (!selectedCampaign) return;
    setResolvingAudience(true);
    setPageError("");
    setNotice("");
    try {
      const envelope = await apiRequest<ApiEnvelope<AudienceResponse>>(
        `/api/campaigns/${selectedCampaign.id}/audience/resolve/`,
        {
          method: "POST",
          body: JSON.stringify({
            selection: {
              list_ids: audienceListIds,
              contact_ids: selectedContactIds,
            },
          }),
        },
      );
      setAudienceResult(unwrap(envelope).audience_snapshot);
      setResolvedCampaignId(selectedCampaign.id);
      setNotice("Audience snapshot saved. Only consented, eligible contacts are included.");
      await loadResources();
    } catch (error) {
      setAudienceResult(null);
      setPageError(
        error instanceof Error ? error.message : "The campaign audience could not be resolved.",
      );
    } finally {
      setResolvingAudience(false);
    }
  }

  async function sendCampaign() {
    if (!selectedCampaign || !audienceResult || !audienceIsCurrent) return;
    const confirmed = window.confirm(
      `Queue “${selectedCampaign.title || "Untitled campaign"}” for ${audienceResult.recipient_count} eligible recipients?`,
    );
    if (!confirmed) return;
    setSending(true);
    setPageError("");
    try {
      const envelope = await apiRequest<
        ApiEnvelope<DeliveryResponse>
      >(`/api/campaigns/${selectedCampaign.id}/send/`, { method: "POST" });
      unwrap(envelope);
      setNotice(`Delivery queued for ${audienceResult.recipient_count} recipients.`);
      await Promise.all([loadResources(), loadSummary(0, selectedCampaign.id)]);
    } catch (error) {
      setPageError(
        error instanceof Error ? error.message : "The campaign could not be queued.",
      );
    } finally {
      setSending(false);
    }
  }

  async function scheduleCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedCampaign || !audienceResult || !audienceIsCurrent || !scheduledFor) {
      return;
    }
    setScheduling(true);
    setPageError("");
    try {
      const envelope = await apiRequest<
        ApiEnvelope<DeliveryResponse>
      >(`/api/campaigns/${selectedCampaign.id}/schedule/`, {
        method: "POST",
        body: JSON.stringify({ scheduled_for: new Date(scheduledFor).toISOString() }),
      });
      const job = unwrap(envelope).delivery_job;
      setNotice(`Campaign scheduled for ${formatDate(job.scheduled_for)}.`);
      setScheduledFor("");
      await Promise.all([loadResources(), loadSummary(0, selectedCampaign.id)]);
    } catch (error) {
      setPageError(
        error instanceof Error ? error.message : "The campaign could not be scheduled.",
      );
    } finally {
      setScheduling(false);
    }
  }

  async function cancelSchedule() {
    if (!selectedCampaign) return;
    setPageError("");
    try {
      await apiRequest<ApiEnvelope<{ status: string }>>(
        `/api/email-delivery/campaigns/${selectedCampaign.id}/cancel-schedule/`,
        { method: "POST" },
      );
      setNotice("Scheduled delivery canceled.");
      await Promise.all([loadResources(), loadSummary(0, selectedCampaign.id)]);
    } catch (error) {
      setPageError(
        error instanceof Error ? error.message : "The schedule could not be canceled.",
      );
    }
  }

  if (!hydrated) {
    return (
      <main className="contacts-page">
        <div className="contacts-loading">Loading your workspace…</div>
      </main>
    );
  }

  if (!accessToken) {
    return (
      <main className="contacts-page">
        <header className="topbar">
          <Link className="brand-lockup brand-link" href="/">
            <span className="brand-mark">Y</span>
            <span className="brand-copy">
              <strong>Yo-kai Mail</strong>
              <span>Contacts & delivery</span>
            </span>
          </Link>
          <Link className="topbar-link" href="/">
            Generation demo
          </Link>
        </header>
        <section className="contacts-login-wrap">
          <form className="contacts-login-card" onSubmit={signIn}>
            <p className="eyebrow">TEAM WORKSPACE</p>
            <h1>Sign in to manage contacts.</h1>
            <p className="contacts-muted">
              Your contacts, lists and campaign activity are private to your account.
            </p>
            <label className="contacts-field">
              <span>Username</span>
              <input
                autoComplete="username"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label className="contacts-field">
              <span>Password</span>
              <input
                autoComplete="current-password"
                required
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {loginError && <div className="contacts-alert error">{loginError}</div>}
            <button className="contacts-primary" disabled={signingIn} type="submit">
              {signingIn ? "Signing in…" : "Sign in"}
            </button>
            <p className="contacts-footnote">
              Use your workspace username and password. If you do not have an account yet, ask your administrator to create one.
            </p>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="contacts-page">
      <header className="topbar">
        <Link className="brand-lockup brand-link" href="/">
          <span className="brand-mark">Y</span>
          <span className="brand-copy">
            <strong>Yo-kai Mail</strong>
            <span>Contacts & delivery</span>
          </span>
        </Link>
        <div className="topbar-actions">
          <Link className="topbar-link" href="/">
            Generation demo
          </Link>
          <button className="signout-button" onClick={clearAuth} type="button">
            Sign out
          </button>
        </div>
      </header>

      <div className="contacts-shell">
        <section className="contacts-heading">
          <div>
            <p className="eyebrow">CONTACTS · DELIVERY · RESEND</p>
            <h1>Reach the right people.</h1>
            <p>
              Keep permission-based contacts organized, resolve a campaign audience, and follow delivery from one place.
            </p>
          </div>
          <button
            className="contacts-secondary refresh-button"
            disabled={loading}
            onClick={() => void loadResources()}
            type="button"
          >
            {loading ? "Refreshing…" : "Refresh workspace"}
          </button>
        </section>

        <nav className="contacts-tabs" aria-label="Audience operations">
          <button
            aria-current={activePanel === "contacts" ? "page" : undefined}
            className={activePanel === "contacts" ? "active" : ""}
            onClick={() => setActivePanel("contacts")}
            type="button"
          >
            Contacts & lists
          </button>
          <button
            aria-current={activePanel === "delivery" ? "page" : undefined}
            className={activePanel === "delivery" ? "active" : ""}
            onClick={() => setActivePanel("delivery")}
            type="button"
          >
            Campaign delivery
          </button>
        </nav>

        {pageError && (
          <div className="contacts-alert error" role="alert">
            <strong>Could not complete that action</strong>
            <span>{pageError}</span>
          </div>
        )}
        {notice && (
          <div className="contacts-alert success" role="status">
            {notice}
          </div>
        )}

        {activePanel === "contacts" ? (
          <div className="contacts-grid">
            <section className="contacts-card import-card">
              <div className="contacts-card-heading">
                <div>
                  <p className="eyebrow">CSV IMPORT</p>
                  <h2>Bring in a contact list.</h2>
                </div>
                <button className="text-action" onClick={downloadContactTemplate} type="button">
                  Download template
                </button>
              </div>
              <p className="contacts-muted">
                CSV needs an <code>email</code> column. Contacts need documented permission to receive email before they are eligible for campaigns.
              </p>
              <form className="import-form" onSubmit={importCsv}>
                <label className="contacts-field">
                  <span>Add imported contacts to</span>
                  <select value={listFilter} onChange={(event) => setListFilter(event.target.value)}>
                    <option value="">All contacts (no list)</option>
                    {contactLists.map((list) => (
                      <option key={list.id} value={list.id}>
                        {list.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="csv-picker">
                  <input accept=".csv,text/csv" onChange={handleCsvFile} type="file" />
                  <span className="csv-picker-icon">↑</span>
                  <span>
                    <strong>{csvFile?.name ?? "Choose a CSV file"}</strong>
                    <small>UTF-8 · up to 5 MB</small>
                  </span>
                </label>
                <button className="contacts-primary" disabled={!csvFile || importing} type="submit">
                  {importing ? "Importing contacts…" : "Import contacts"}
                </button>
              </form>
              {importSummary && (
                <div className="import-summary" role="status">
                  <div><span>Accepted</span><strong>{importSummary.accepted}</strong></div>
                  <div><span>Duplicate</span><strong>{importSummary.duplicate}</strong></div>
                  <div><span>Invalid</span><strong>{importSummary.invalid}</strong></div>
                  <div><span>Skipped</span><strong>{importSummary.skipped}</strong></div>
                  {importSummary.row_errors.length > 0 && (
                    <details className="row-errors">
                      <summary>Show row notes ({importSummary.row_errors.length})</summary>
                      <ul>
                        {importSummary.row_errors.map((row) => (
                          <li key={`${row.row}-${row.reason}`}>Row {row.row}: {row.reason}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              )}
              <p className="contacts-footnote">
                To record permission in the CSV, set <code>consent_status</code> to <code>granted</code> and provide <code>consented_at</code>. Unsubscribed and suppressed contacts are never added to a send audience.
              </p>
            </section>

            <section className="contacts-card list-card">
              <div className="contacts-card-heading">
                <div>
                  <p className="eyebrow">SEGMENTS</p>
                  <h2>Your contact lists</h2>
                </div>
                <span className="count-chip">{contactLists.length} lists</span>
              </div>
              <form className="list-create-form" onSubmit={createContactList}>
                <label className="contacts-field">
                  <span>List name</span>
                  <input
                    maxLength={160}
                    placeholder="Spring launch"
                    required
                    value={listName}
                    onChange={(event) => setListName(event.target.value)}
                  />
                </label>
                <label className="contacts-field">
                  <span>Description <em>optional</em></span>
                  <input
                    maxLength={500}
                    placeholder="Customers who opted into product news"
                    value={listDescription}
                    onChange={(event) => setListDescription(event.target.value)}
                  />
                </label>
                <button className="contacts-secondary" disabled={creatingList || !listName.trim()} type="submit">
                  {creatingList ? "Creating…" : "Create list"}
                </button>
              </form>
              <div className="list-stack">
                {contactLists.length === 0 ? (
                  <p className="empty-note">No lists yet. Create one or choose a list during CSV import.</p>
                ) : (
                  contactLists.map((list) => (
                    <button
                      aria-pressed={listFilter === list.id}
                      className={`list-row ${listFilter === list.id ? "selected" : ""}`}
                      key={list.id}
                      onClick={() => setListFilter((current) => current === list.id ? "" : list.id)}
                      type="button"
                    >
                      <span className="list-avatar">{list.name.slice(0, 1).toUpperCase()}</span>
                      <span className="list-row-copy">
                        <strong>{list.name}</strong>
                        <small>{list.description || "Contact segment"}</small>
                      </span>
                      <span className="list-members">{list.member_count}</span>
                    </button>
                  ))
                )}
              </div>
            </section>

            <section className="contacts-card contact-table-card">
              <div className="contacts-card-heading contact-table-heading">
                <div>
                  <p className="eyebrow">CONTACTS</p>
                  <h2>{listFilter ? "List members" : "All contacts"}</h2>
                </div>
                <div className="table-tools">
                  <span className="count-chip">{visibleContacts.length} shown</span>
                  <input
                    aria-label="Search contacts"
                    className="contact-search"
                    placeholder="Search email or name"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </div>
              </div>
              {selectedContactIds.length > 0 && (
                <div className="selection-bar">
                  <span>{selectedContactIds.length} selected</span>
                  <select value={membershipListId} onChange={(event) => setMembershipListId(event.target.value)}>
                    <option value="">Choose a list</option>
                    {contactLists.map((list) => <option key={list.id} value={list.id}>{list.name}</option>)}
                  </select>
                  <button
                    className="text-action"
                    disabled={!membershipListId}
                    onClick={() => void addSelectedContacts()}
                    type="button"
                  >
                    Add to list
                  </button>
                  <button className="text-action muted-action" onClick={() => setSelectedContactIds([])} type="button">
                    Clear
                  </button>
                </div>
              )}
              <div className="contact-table-wrap">
                <table className="contact-table">
                  <thead>
                    <tr>
                      <th><span className="sr-only">Select</span></th>
                      <th>Contact</th>
                      <th>Status</th>
                      <th>Consent</th>
                      <th>Source</th>
                      <th><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleContacts.length === 0 ? (
                      <tr><td className="table-empty" colSpan={6}>{loading ? "Loading contacts…" : "No contacts found. Import a CSV to get started."}</td></tr>
                    ) : visibleContacts.slice(0, 200).map((contact) => (
                      <tr key={contact.id}>
                        <td>
                          <input
                            aria-label={`Select ${contact.email}`}
                            checked={selectedContactIds.includes(contact.id)}
                            onChange={(event) => {
                              setSelectedContactIds((current) => event.target.checked
                                ? [...current, contact.id]
                                : current.filter((id) => id !== contact.id));
                              setAudienceResult(null);
                            }}
                            type="checkbox"
                          />
                        </td>
                        <td>
                          <strong>{contact.display_name || [contact.first_name, contact.last_name].filter(Boolean).join(" ") || contact.email}</strong>
                          <small>{contact.email}</small>
                        </td>
                        <td><span className={`status-tag status-${contact.status}`}>{statusLabel(contact.status)}</span></td>
                        <td><span className="consent-copy">{statusLabel(contact.consent_status)}</span></td>
                        <td>{contact.source || "—"}</td>
                        <td>
                          {contact.status === "active" && (
                            <button className="text-action danger-action" onClick={() => void unsubscribeContact(contact)} type="button">
                              Unsubscribe
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {visibleContacts.length > 200 && (
                <p className="contacts-footnote">Showing the first 200 matches. Narrow the search to find a contact.</p>
              )}
              <p className="contacts-footnote">
                Selecting contacts here lets you include individuals in a campaign audience. Permission and suppression rules are checked again before recipients are resolved.
              </p>
            </section>
          </div>
        ) : (
          <div className="delivery-layout">
            <section className="contacts-card delivery-setup-card">
              <div className="contacts-card-heading">
                <div>
                  <p className="eyebrow">CAMPAIGN DELIVERY</p>
                  <h2>Choose an approved campaign.</h2>
                </div>
                <span className="count-chip">{campaigns.length} campaigns</span>
              </div>
              <div className="delivery-campaign-picker">
                <label className="contacts-field">
                  <span>Campaign</span>
                  <select
                    value={selectedCampaignId}
                    onChange={(event) => {
                      setSelectedCampaignId(event.target.value);
                      setAudienceResult(null);
                      setResolvedCampaignId("");
                    }}
                  >
                    <option value="">Choose a saved campaign</option>
                    {campaigns.map((campaign) => (
                      <option key={campaign.id} value={campaign.id}>
                        {campaign.title || "Untitled campaign"} · {statusLabel(campaign.status)}
                      </option>
                    ))}
                  </select>
                </label>
                {selectedCampaign ? (
                  <div className="campaign-context">
                    <div className="campaign-context-top">
                      <span className={`status-tag status-${selectedCampaign.status}`}>{statusLabel(selectedCampaign.status)}</span>
                      {selectedCampaign.active_design && <span className="consent-copy">Design v{selectedCampaign.active_design.version}</span>}
                    </div>
                    <strong>{selectedCampaign.title || "Untitled campaign"}</strong>
                    <a href={selectedCampaign.source_url} rel="noreferrer" target="_blank">{selectedCampaign.source_url}</a>
                    {selectedCampaign.scheduled_for && <small>Scheduled for {formatDate(selectedCampaign.scheduled_for)}</small>}
                    {selectedCampaign.status !== "ready" && selectedCampaign.status !== "scheduled" && (
                      <p className="contacts-footnote">A campaign must be reviewed and marked ready before it can be sent.</p>
                    )}
                  </div>
                ) : campaigns.length === 0 ? (
                  <div className="empty-delivery">
                    <strong>No campaigns are connected to your account yet.</strong>
                    <span>Campaign delivery needs a saved design that has been reviewed and marked ready. The generation demo can send one-recipient tests, but does not save campaign records.</span>
                    <Link href="/">Open generation demo</Link>
                  </div>
                ) : null}
              </div>

              {selectedCampaign && (
                <>
                  <div className="audience-picker">
                    <div className="contacts-card-heading">
                      <div>
                        <p className="eyebrow">AUDIENCE</p>
                        <h3>Resolve recipients.</h3>
                      </div>
                      <span className="count-chip">{selectedContactIds.length} individual contacts selected</span>
                    </div>
                    <p className="contacts-muted">
                      Choose one or more lists, or select individual contacts in Contacts & lists. Only unique contacts with active, recorded permission are included.
                    </p>
                    <div className="audience-list-options">
                      {contactLists.length === 0 ? (
                        <p className="empty-note">Create a list or select contacts before resolving an audience.</p>
                      ) : contactLists.map((list) => (
                        <label className="audience-list-option" key={list.id}>
                          <input
                            checked={audienceListIds.includes(list.id)}
                            onChange={(event) => {
                              setAudienceListIds((current) => event.target.checked
                                ? [...current, list.id]
                                : current.filter((id) => id !== list.id));
                              setAudienceResult(null);
                            }}
                            type="checkbox"
                          />
                          <span><strong>{list.name}</strong><small>{list.member_count} contacts</small></span>
                        </label>
                      ))}
                    </div>
                    <div className="audience-actions">
                      <button
                        className="contacts-primary"
                        disabled={!canResolveAudience || resolvingAudience || (audienceListIds.length === 0 && selectedContactIds.length === 0)}
                        onClick={() => void resolveAudience()}
                        type="button"
                      >
                        {resolvingAudience ? "Resolving audience…" : "Resolve and save audience"}
                      </button>
                      {audienceResult && audienceIsCurrent && (
                        <div className="audience-result" role="status">
                          <strong>{audienceResult.recipient_count} eligible recipients</strong>
                          <span>{audienceResult.excluded_count} contacts excluded by status or consent</span>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="send-controls">
                    {selectedCampaign.status === "ready" ? (
                      <>
                        <button
                          className="contacts-primary send-now-button"
                          disabled={!audienceIsCurrent || !audienceResult?.recipient_count || sending}
                          onClick={() => void sendCampaign()}
                          type="button"
                        >
                          {sending ? "Queuing delivery…" : "Send campaign now"}
                        </button>
                        <form className="schedule-form" onSubmit={scheduleCampaign}>
                          <label className="contacts-field">
                            <span>Schedule for your local time</span>
                            <input
                              min={localDateTimeMinimum()}
                              required
                              type="datetime-local"
                              value={scheduledFor}
                              onChange={(event) => setScheduledFor(event.target.value)}
                            />
                          </label>
                          <button className="contacts-secondary" disabled={!audienceIsCurrent || !audienceResult?.recipient_count || scheduling} type="submit">
                            {scheduling ? "Scheduling…" : "Schedule campaign"}
                          </button>
                        </form>
                      </>
                    ) : selectedCampaign.status === "scheduled" ? (
                      <button className="contacts-secondary cancel-schedule" onClick={() => void cancelSchedule()} type="button">
                        Cancel scheduled delivery
                      </button>
                    ) : (
                      <div className="send-disabled-note">
                        Campaign send actions unlock after the campaign is approved and marked ready.
                      </div>
                    )}
                    <p className="contacts-footnote">
                      Campaign sends use the saved, eligible audience and never accept pasted recipient addresses. Test emails remain a separate one-recipient workflow on the generation demo. If delivery is unavailable, ask your administrator to check the sending service.
                    </p>
                  </div>
                </>
              )}
            </section>

            <section className="contacts-card delivery-summary-card">
              <div className="contacts-card-heading">
                <div>
                  <p className="eyebrow">DELIVERY ACTIVITY</p>
                  <h2>Campaign results</h2>
                </div>
                <button
                  className="text-action"
                  disabled={!selectedCampaignId || summaryLoading}
                  onClick={() => void loadSummary(0)}
                  type="button"
                >
                  {summaryLoading ? "Updating…" : "Refresh"}
                </button>
              </div>
              {!selectedCampaignId ? (
                <p className="empty-note">Choose a campaign to view delivery activity.</p>
              ) : summaryLoading && !summary ? (
                <p className="empty-note">Loading campaign activity…</p>
              ) : summary ? (
                <>
                  <div className="delivery-count-grid">
                    {[
                      ["Queued", summary.counts.queued],
                      ["Sent", summary.counts.sent],
                      ["Delivered", summary.counts.delivered],
                      ["Bounced", summary.counts.bounced],
                      ["Failed", summary.counts.failed],
                      ["Complained", summary.counts.complained],
                    ].map(([label, value]) => (
                      <div className="delivery-count" key={label}>
                        <span>{label}</span><strong>{value}</strong>
                      </div>
                    ))}
                  </div>
                  {summary.job && (
                    <div className="job-status-row">
                      <span>Latest job</span>
                      <strong className={`status-tag status-${summary.job.status}`}>{statusLabel(summary.job.status)}</strong>
                      {summary.job.scheduled_for && <small>{formatDate(summary.job.scheduled_for)}</small>}
                    </div>
                  )}
                  {summary.job?.error_summary && <div className="contacts-alert error">{summary.job.error_summary}</div>}
                  <div className="recipient-heading">
                    <div><strong>Recipient activity</strong><span>{summary.recipients.total} total</span></div>
                  </div>
                  <div className="recipient-list">
                    {summary.recipients.items.length === 0 ? (
                      <p className="empty-note">No recipient delivery records yet.</p>
                    ) : summary.recipients.items.map((recipient) => (
                      <div className="recipient-row" key={recipient.id}>
                        <div className="recipient-main">
                          <strong>{recipient.recipient_email}</strong>
                          <small>{recipient.last_event_type ? statusLabel(recipient.last_event_type.replace(/^email\./, "")) : "Waiting for delivery update"}</small>
                        </div>
                        <div className="recipient-meta">
                          <span className={`status-tag status-${recipient.status}`}>{statusLabel(recipient.status)}</span>
                          <small>{formatDate(recipient.last_event_at || recipient.sent_at)}</small>
                        </div>
                        {recipient.failure_reason && <p className="recipient-failure">{recipient.failure_reason}</p>}
                        {recipient.provider_message_id && (
                          <details className="provider-receipt">
                            <summary>Provider receipt</summary>
                            <code>{recipient.provider_message_id}</code>
                          </details>
                        )}
                      </div>
                    ))}
                  </div>
                  {summary.recipients.total > summary.recipients.limit && (
                    <div className="recipient-pagination">
                      <button
                        className="contacts-secondary"
                        disabled={summary.recipients.offset === 0 || summaryLoading}
                        onClick={() => void loadSummary(Math.max(0, summary.recipients.offset - summary.recipients.limit))}
                        type="button"
                      >Previous</button>
                      <span>{summary.recipients.offset + 1}–{Math.min(summary.recipients.offset + summary.recipients.items.length, summary.recipients.total)} of {summary.recipients.total}</span>
                      <button
                        className="contacts-secondary"
                        disabled={summary.recipients.offset + summary.recipients.limit >= summary.recipients.total || summaryLoading}
                        onClick={() => void loadSummary(summary.recipients.offset + summary.recipients.limit)}
                        type="button"
                      >Next</button>
                    </div>
                  )}
                </>
              ) : (
                <p className="empty-note">Campaign activity is not available yet.</p>
              )}
            </section>
          </div>
        )}
      </div>
    </main>
  );
}
