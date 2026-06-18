import { useCallback, useEffect, useState } from "react";
import { getMigrations, postMigrations } from "../api";
import { EAST_AFRICA_ENV_TEMPLATE } from "../envEastAfricaTemplate";
import { Card, Field, Output, StatusBadge } from "../components/ui";

type SetupTask = {
  id: string;
  service: string;
  title: string;
  status: string;
  category?: string;
  issues: Array<{
    id: string;
    severity: string;
    title: string;
    detail: string;
    resolution: string;
    autoFixable: boolean;
    autoActionId: string;
    autoActionLabel?: string;
  }>;
  autoActions: Array<{ id: string; label: string }>;
};

type SetupAudit = {
  summary: {
    totalTasks: number;
    ready: number;
    needsAttention: number;
    autoFixableIssues: number;
    platformUrl?: string;
    migrationReady?: number;
    migrationTotal?: number;
    billingReady?: number;
    billingTotal?: number;
  };
  tasks: SetupTask[];
  suggestedEnv?: string;
  envTemplate?: string;
  envTemplatePath?: string;
  stripeInstallerSources?: Array<{
    serviceName: string;
    repoUrl?: string | null;
    stripeKeysOnRailway?: string[];
    githubStripeKeys?: string[];
    hasStripeSecret?: boolean;
  }>;
  globalAutoActions?: Array<{ id: string; label: string }>;
};

const SETUP_SECTIONS: Array<{ category: string; title: string; hint: string }> = [
  {
    category: "foundation",
    title: "Foundation",
    hint: "Required for sealing secrets in every migration plan.",
  },
  {
    category: "migration",
    title: "Migration & deploy APIs (core transfer)",
    hint: "Railway, Render, Fly, Orena, Supabase, Cloudflare, GitHub — powers Account review → Discover → Transfer → Deploy.",
  },
  {
    category: "billing",
    title: "Platform billing (API Transfer subscriptions)",
    hint: "Stripe and Paystack bill your customers for API Transfer plans — separate from migrating a client's app.",
  },
];

const PREWIRE_SERVICES: Array<{ id: string; label: string }> = [
  { id: "railway", label: "Railway" },
  { id: "render", label: "Render" },
  { id: "fly", label: "Fly.io" },
  { id: "orena", label: "Orena" },
  { id: "supabase", label: "Supabase" },
  { id: "cloudflare", label: "Cloudflare" },
  { id: "paystack", label: "Paystack (client billing)" },
  { id: "monitoring", label: "Monitoring" },
  { id: "backups", label: "Backups" },
];

const DEFAULT_PREWIRE_SERVICES = ["railway", "render", "orena", "supabase", "cloudflare", "monitoring", "backups"];

function actionLabel(task: SetupTask, actionId: string, override?: string): string {
  if (override) return override;
  const match = task.autoActions.find((action) => action.id === actionId);
  return match?.label || actionId.replace(/_/g, " ");
}

function SetupActionButton({
  actionId,
  label,
  busyAction,
  disabled,
  onRun,
}: {
  actionId: string;
  label: string;
  busyAction: string | null;
  disabled?: boolean;
  onRun: (id: string) => void;
}) {
  const busy = busyAction === actionId;
  return (
    <button
      type="button"
      className="btn btn-action btn-sm"
      disabled={disabled || busyAction !== null}
      onClick={() => onRun(actionId)}
    >
      {busy ? "Running…" : label}
    </button>
  );
}

function SetupTaskBlock({
  task,
  demoMode,
  busyAction,
  onRunAction,
}: {
  task: SetupTask;
  demoMode: boolean;
  busyAction: string | null;
  onRunAction: (id: string) => void;
}) {
  const issueActionIds = new Set(
    task.issues.filter((issue) => issue.autoFixable && issue.autoActionId).map((issue) => issue.autoActionId),
  );
  const standaloneActions = task.autoActions.filter((action) => !issueActionIds.has(action.id));

  return (
    <div className="setup-task">
      <div className="provider-head">
        <strong>{task.title}</strong>
        <StatusBadge
          ok={task.status === "ready"}
          label={task.status === "ready" ? "Ready" : task.status === "partial" ? "Partial" : "Missing"}
        />
      </div>
      {task.issues.map((issue) => (
        <div className="setup-issue" key={issue.id}>
          <p>
            <strong>{issue.title}</strong> — {issue.detail}
          </p>
          <p className="muted small">{issue.resolution}</p>
          {issue.autoFixable && issue.autoActionId && !demoMode && (
            <SetupActionButton
              actionId={issue.autoActionId}
              label={actionLabel(task, issue.autoActionId, issue.autoActionLabel)}
              busyAction={busyAction}
              onRun={onRunAction}
            />
          )}
        </div>
      ))}
      {standaloneActions.length > 0 && (
        <div className="setup-actions">
          {standaloneActions.map((action) => (
            <SetupActionButton
              key={action.id}
              actionId={action.id}
              label={action.label}
              busyAction={busyAction}
              disabled={demoMode}
              onRun={onRunAction}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function PlatformSetup({
  demoMode = false,
  bootstrapSetup,
  onConfigChanged,
}: {
  demoMode?: boolean;
  bootstrapSetup?: SetupAudit | null;
  onConfigChanged?: () => void | Promise<void>;
}) {
  const [audit, setAudit] = useState<SetupAudit | null>(bootstrapSetup ?? null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<any>(null);
  const [out, setOut] = useState<unknown>("");

  const [clientEmail, setClientEmail] = useState("");
  const [clientName, setClientName] = useState("");
  const [clientDomain, setClientDomain] = useState("");
  const [targetProvider, setTargetProvider] = useState("orena");
  const [targetRegion, setTargetRegion] = useState("ke-1");
  const [sourceProvider, setSourceProvider] = useState("railway");
  const [appIdentifier, setAppIdentifier] = useState("");
  const [prewireServices, setPrewireServices] = useState<string[]>(DEFAULT_PREWIRE_SERVICES);
  const [prewireResult, setPrewireResult] = useState<any>(null);
  const [stripeSecretInput, setStripeSecretInput] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const loadAudit = useCallback(async () => {
    try {
      setOut("Auditing platform configuration...");
      const data = await getMigrations("/platform/setup-audit");
      setAudit(data);
      setOut("");
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    if (!bootstrapSetup && !demoMode) {
      void loadAudit();
    }
  }, [bootstrapSetup, demoMode, loadAudit]);

  async function runAction(actionId: string) {
    try {
      setBusyAction(actionId);
      setLastResult(null);
      setActionError(null);
      const data = await postMigrations("/platform/setup-run", { actionId, applyToEnv: true });
      setLastResult(data);
      if (!data.ok) {
        setActionError(data.message || "Setup action failed.");
        setOut(data);
      } else {
        setActionError(null);
        if (data.suggestedEnv) {
          setOut({ message: data.message, suggestedEnv: data.suggestedEnv });
        } else {
          setOut(data);
        }
      }
      await loadAudit();
      if (data.appliedToEnv && onConfigChanged) {
        await onConfigChanged();
      }
    } catch (e) {
      const message = (e as Error).message;
      setActionError(message);
      setOut(`Error: ${message}`);
    } finally {
      setBusyAction(null);
    }
  }

  async function saveStripeSecret() {
    const secret = stripeSecretInput.trim();
    if (!secret.startsWith("sk_")) {
      setActionError("Paste a Stripe secret key (starts with sk_test_ or sk_live_).");
      return;
    }
    try {
      setBusyAction("apply_platform_env");
      setActionError(null);
      const data = await postMigrations("/platform/setup-run", {
        actionId: "apply_platform_env",
        applyToEnv: true,
        envVars: { STRIPE_SECRET_KEY: secret },
      });
      setLastResult(data);
      if (!data.ok) {
        setActionError(data.message || "Could not save Stripe secret.");
      } else {
        setActionError(null);
        setStripeSecretInput("");
        setOut(data);
      }
      await loadAudit();
      if (data.appliedToEnv && onConfigChanged) {
        await onConfigChanged();
      }
    } catch (e) {
      const message = (e as Error).message;
      setActionError(
        `${message} If you saw a server error, check .env — the key may still have been saved. Restart Django and refresh providers.`,
      );
      setOut(`Error: ${message}`);
    } finally {
      setBusyAction(null);
    }
  }

  function togglePrewireService(id: string) {
    setPrewireServices((current) => (current.includes(id) ? current.filter((s) => s !== id) : [...current, id]));
  }

  async function onPrewireClient() {
    try {
      setOut("Prewiring client workspace...");
      const data = await postMigrations("/clients/prewire", {
        clientEmail,
        clientName: clientName || undefined,
        clientDomain,
        targetProvider,
        targetRegion,
        sourceProvider: appIdentifier ? sourceProvider : "",
        appIdentifier: appIdentifier || "",
        services: prewireServices,
        runDiscover: Boolean(appIdentifier),
      });
      setPrewireResult(data);
      setOut(data);
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  const [copied, setCopied] = useState(false);
  const envTemplate = audit?.envTemplate || EAST_AFRICA_ENV_TEMPLATE;

  async function copyTemplate() {
    await navigator.clipboard.writeText(envTemplate);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const summary = audit?.summary;

  return (
    <>
      <Card
        title="Platform setup automation"
        hint="Configure server-side API keys in .env, then verify live connections. Migration providers drive automated transfer; billing providers sell API Transfer subscriptions."
      >
        <p className="muted small">
          <strong>Core workflow:</strong> Account review (Railway/Render/Orena) → Discover → Plan → Apply → Transfer →
          Deploy. Stripe/Paystack on the pricing page are for <em>your platform&apos;s</em> subscription checkout — not
          the same as wiring Railway for live API transfers.
        </p>
        {audit?.stripeInstallerSources && audit.stripeInstallerSources.length > 0 && (
          <div className="notice deploy-live setup-highlight-banner">
            <p>
              <strong>Stripe Installer detected on Railway:</strong>{" "}
              {audit.stripeInstallerSources.map((s) => s.serviceName).join(", ")}
              {audit.stripeInstallerSources[0]?.repoUrl && (
                <>
                  {" "}
                  · GitHub{" "}
                  <a href={audit.stripeInstallerSources[0].repoUrl!} target="_blank" rel="noreferrer">
                    {audit.stripeInstallerSources[0].repoUrl}
                  </a>
                </>
              )}
            </p>
            <p className="muted small">
              Railway already has Stripe keys — sync them into this server&apos;s <code>.env</code> with one click.
            </p>
            {!demoMode && (
              <SetupActionButton
                actionId="sync_stripe_from_railway"
                label="Sync Stripe from Railway (Stripe Installer)"
                busyAction={busyAction}
                onRun={(id) => void runAction(id)}
              />
            )}
          </div>
        )}
        {(actionError || lastResult?.needsManualSecret) && !demoMode && (
          <div className="notice setup-error-banner">
            <p>
              <strong>{actionError || lastResult?.message}</strong>
            </p>
            {lastResult?.appliedToEnv && lastResult?.partialEnv && (
              <p className="muted small">
                Saved partial keys: {Object.keys(lastResult.partialEnv).join(", ")}. STRIPE_SECRET_KEY is still
                required for Stripe to show Live.
              </p>
            )}
            <Field label="Stripe secret key (from Stripe Dashboard → Developers → API keys)">
              <input
                type="password"
                autoComplete="off"
                placeholder="sk_test_… or sk_live_…"
                value={stripeSecretInput}
                onChange={(e) => setStripeSecretInput(e.target.value)}
              />
            </Field>
            <SetupActionButton
              actionId="apply_platform_env"
              label="Save Stripe secret to .env"
              busyAction={busyAction}
              onRun={() => void saveStripeSecret()}
            />
          </div>
        )}
        {summary && (
          <div className="account-strip">
            <div>
              <span className="muted small">Migration APIs ready</span>
              <strong>
                {summary.migrationReady ?? "—"}/{summary.migrationTotal ?? "—"}
              </strong>
            </div>
            <div>
              <span className="muted small">Billing ready</span>
              <strong>
                {summary.billingReady ?? "—"}/{summary.billingTotal ?? "—"}
              </strong>
            </div>
            <div>
              <span className="muted small">All tasks</span>
              <strong>
                {summary.ready}/{summary.totalTasks}
              </strong>
            </div>
            <div>
              <span className="muted small">Needs attention</span>
              <StatusBadge ok={summary.needsAttention === 0} label={String(summary.needsAttention)} />
            </div>
          </div>
        )}
        <div className="row setup-toolbar">
          <button className="btn btn-outline" disabled={demoMode || busyAction !== null} onClick={() => void loadAudit()}>
            Re-audit platform
          </button>
          {!demoMode &&
            audit?.globalAutoActions?.map((action) => (
              <SetupActionButton
                key={action.id}
                actionId={action.id}
                label={action.label}
                busyAction={busyAction}
                onRun={(id) => void runAction(id)}
              />
            ))}
        </div>

        {audit?.tasks && (
          <div className="setup-tasks">
            {SETUP_SECTIONS.map((section) => {
              const sectionTasks = audit.tasks.filter((t) => (t.category || "migration") === section.category);
              if (sectionTasks.length === 0) return null;
              return (
                <div className="setup-section" key={section.category}>
                  <h3>{section.title}</h3>
                  <p className="muted small">{section.hint}</p>
                  {sectionTasks.map((task) => (
                    <SetupTaskBlock
                      key={task.id}
                      task={task}
                      demoMode={demoMode}
                      busyAction={busyAction}
                      onRunAction={(id) => void runAction(id)}
                    />
                  ))}
                </div>
              );
            })}
          </div>
        )}

        {audit?.suggestedEnv && (
          <Field label="Suggested .env (copy missing values)">
            <textarea className="code" rows={6} readOnly spellCheck={false} value={audit.suggestedEnv} />
          </Field>
        )}

        {(lastResult?.suggestedEnvText || lastResult?.suggestedEnv) && (
          <Field
            label={
              lastResult?.appliedToEnv
                ? "Applied to .env (also copied below for your records)"
                : "Action output — add to .env manually (hosted deploy)"
            }
          >
            <textarea
              className="code"
              rows={4}
              readOnly
              spellCheck={false}
              value={
                lastResult.suggestedEnvText ||
                Object.entries(lastResult.suggestedEnv)
                  .map(([k, v]) => `${k}=${v}`)
                  .join("\n")
              }
            />
          </Field>
        )}
        {lastResult?.appliedToEnv && (
          <p className="notice deploy-live">
            <strong>Applied to .env</strong> — {lastResult.appliedKeys?.join(", ") || "keys updated"}. Provider
            readiness refreshes automatically.
          </p>
        )}
        <Output value={out} />
      </Card>

      <Card
        title="Prewire new client"
        hint="Links a client workspace to migration providers (Railway, Render, Orena, etc.) after platform .env is configured."
      >
        <div className="row">
          <Field label="Client email">
            <input type="email" value={clientEmail} onChange={(e) => setClientEmail(e.target.value)} />
          </Field>
          <Field label="Client / workspace name">
            <input value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="Acme Ltd" />
          </Field>
        </div>
        <div className="row">
          <Field label="Licensed domain">
            <input value={clientDomain} onChange={(e) => setClientDomain(e.target.value)} placeholder="app.client.co.ke" />
          </Field>
          <Field label="Target provider">
            <select value={targetProvider} onChange={(e) => setTargetProvider(e.target.value)}>
              <option value="orena">orena (Nairobi ke-1)</option>
              <option value="railway">railway</option>
              <option value="render">render</option>
              <option value="fly">fly</option>
            </select>
          </Field>
          <Field label="Target region">
            <input value={targetRegion} onChange={(e) => setTargetRegion(e.target.value)} placeholder="ke-1" />
          </Field>
        </div>
        <div className="row">
          <Field label="Source provider (optional — for discover + plan)">
            <select value={sourceProvider} onChange={(e) => setSourceProvider(e.target.value)}>
              <option value="railway">railway</option>
              <option value="render">render</option>
              <option value="orena">orena</option>
            </select>
          </Field>
          <Field label="Source app ID / name">
            <input value={appIdentifier} onChange={(e) => setAppIdentifier(e.target.value)} placeholder="service-id or name" />
          </Field>
        </div>
        <Field label="Services to prewire">
          <div className="capabilities">
            {PREWIRE_SERVICES.map((service) => (
              <label key={service.id} className="checkbox-label">
                <input
                  type="checkbox"
                  checked={prewireServices.includes(service.id)}
                  onChange={() => togglePrewireService(service.id)}
                />{" "}
                {service.label}
              </label>
            ))}
          </div>
        </Field>
        <button className="btn btn-primary" disabled={demoMode || !clientEmail || !clientDomain} onClick={() => void onPrewireClient()}>
          Prewire client
        </button>

        {prewireResult && (
          <div className="deploy-live">
            <p>
              Status:{" "}
              <StatusBadge ok={prewireResult.ok} label={prewireResult.ok ? "Ready" : "Needs attention"} />
            </p>
            {prewireResult.conflicts?.length > 0 && (
              <ul>
                {prewireResult.conflicts.map((c: any) => (
                  <li key={c.code} className="error">
                    {c.message}
                  </li>
                ))}
              </ul>
            )}
            {prewireResult.checklist && (
              <ul>
                {prewireResult.checklist.map((item: any) => (
                  <li key={item.step}>
                    {item.done ? "✓" : "○"} {item.label}
                  </li>
                ))}
              </ul>
            )}
            {prewireResult.nextSteps && (
              <ol>
                {prewireResult.nextSteps.map((step: string) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            )}
            {prewireResult.discoveryId && (
              <p className="muted small">Discovery ID: {prewireResult.discoveryId}</p>
            )}
          </div>
        )}
      </Card>

      <Card
        title="Full .env template"
        hint="All keys — migration APIs, billing, and East Africa defaults. Paste into .env next to manage.py, restart Django."
      >
        <Field label="Paste into .env (same folder as manage.py)">
          <textarea className="code" rows={16} readOnly spellCheck={false} value={envTemplate} />
        </Field>
        <div className="row">
          <button className="btn btn-primary" type="button" onClick={() => void copyTemplate()}>
            {copied ? "Copied!" : "Copy template to clipboard"}
          </button>
        </div>
      </Card>
    </>
  );
}
