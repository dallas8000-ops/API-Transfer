import { useEffect, useState } from "react";
import { postMigrations } from "../api";
import { Card, Field, Output, StatusBadge } from "../components/ui";
import type { ReviewedApp } from "./AccountReview";

const SAMPLE_SPEC = {
  appName: "demo-app",
  sourceProvider: "render",
  targetProvider: "railway",
  services: [
    {
      name: "web",
      runtime: "node",
      startCommand: "node server.js",
      region: "oregon",
      environment: { NODE_ENV: "production" },
      secrets: [{ key: "API_KEY", sealed: true }],
    },
  ],
  domains: [{ host: "demo-app.example.com", tlsRequired: true }],
  databases: [{ name: "primary", engine: "postgres", version: "16" }],
  metadata: { requestedBy: "ui-user", requestedAt: new Date().toISOString(), environment: "stage" },
};

const PROVIDERS = ["render", "railway", "fly", "kong", "terraform", "supabase"];

const EMPTY_SPEC = {
  appName: "",
  sourceProvider: "render",
  targetProvider: "railway",
  services: [],
  domains: [],
  databases: [],
  metadata: { requestedBy: "ui-user", requestedAt: new Date().toISOString(), environment: "prod" },
};

export function DiscoverPlanApply({
  demoMode = false,
  selectedApp,
  discoveryId: externalDiscoveryId,
  onDiscovery,
}: {
  demoMode?: boolean;
  selectedApp?: { provider: string; app: ReviewedApp } | null;
  discoveryId?: string;
  onDiscovery?: (discoveryId: string) => void;
}) {
  const [provider, setProvider] = useState(selectedApp?.provider || "railway");
  const [appId, setAppId] = useState(selectedApp?.app.id || selectedApp?.app.name || "");
  const [discoveryId, setDiscoveryId] = useState("");
  const [secretKeys, setSecretKeys] = useState<string[]>([]);
  const [discoverOut, setDiscoverOut] = useState<unknown>("");

  const [spec, setSpec] = useState(JSON.stringify(demoMode ? SAMPLE_SPEC : EMPTY_SPEC, null, 2));
  const [plan, setPlan] = useState<any>(null);
  const [planOut, setPlanOut] = useState<unknown>("");

  const [approvedBy, setApprovedBy] = useState("");
  const [applyOut, setApplyOut] = useState<unknown>("");

  useEffect(() => {
    if (!selectedApp) return;
    setProvider(selectedApp.provider);
    setAppId(selectedApp.app.id);
  }, [selectedApp]);

  useEffect(() => {
    if (externalDiscoveryId) setDiscoveryId(externalDiscoveryId);
  }, [externalDiscoveryId]);

  function useSelectedApp() {
    if (!selectedApp) return;
    setProvider(selectedApp.provider);
    setAppId(selectedApp.app.id);
  }

  async function onDiscover() {
    try {
      setDiscoverOut("Discovering...");
      const data = await postMigrations("/discover", { provider, appIdentifier: appId });
      setDiscoverOut(data);
      if (data.spec) setSpec(JSON.stringify(data.spec, null, 2));
      setDiscoveryId(data.discoveryId || "");
      setSecretKeys(data.secretKeys || []);
      onDiscovery?.(data.discoveryId || "");
    } catch (e) {
      setDiscoverOut(`Error: ${(e as Error).message}`);
    }
  }

  async function onPlan() {
    try {
      setPlanOut("Planning...");
      const parsed = JSON.parse(spec);
      const data = await postMigrations("/plan", { spec: parsed });
      setPlan(data.plan);
      setPlanOut(data);
    } catch (e) {
      setPlan(null);
      setPlanOut(`Error: ${(e as Error).message}`);
    }
  }

  async function onApply() {
    try {
      if (!plan) throw new Error("Create a plan first.");
      setApplyOut("Applying...");
      const parsed = JSON.parse(spec);
      const data = await postMigrations("/apply", { spec: parsed, plan, approvedBy });
      setApplyOut(data);
    } catch (e) {
      setApplyOut(`Error: ${(e as Error).message}`);
    }
  }

  return (
    <Card title="Migration plan" hint="Discover a source app, generate a risk-scored plan, then approve and apply. Secret values are sealed server-side and never sent back to the browser.">
      <div className="stepper">
        <div className="step">
          <h4>1. Discover</h4>
          {selectedApp && (
            <button className="btn btn-outline" onClick={useSelectedApp}>
              Use selected app from account review
            </button>
          )}
          <div className="row">
            <Field label="Provider">
              <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                {PROVIDERS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="App identifier">
              <input value={appId} onChange={(e) => setAppId(e.target.value)} placeholder="my-app or project-ref" />
            </Field>
          </div>
          <button className="btn btn-outline" onClick={onDiscover}>
            Discover
          </button>
          {discoveryId && (
            <p className="muted small">
              Discovery vault: {discoveryId}
              {secretKeys.length > 0 ? ` · sealed secrets: ${secretKeys.join(", ")}` : ""}
            </p>
          )}
          <Output value={discoverOut} />
        </div>

        <div className="step">
          <h4>2. Plan</h4>
          <textarea
            className="code"
            rows={12}
            spellCheck={false}
            value={spec}
            onChange={(e) => setSpec(e.target.value)}
          />
          <button className="btn btn-outline" onClick={onPlan}>
            Create plan
          </button>
          {plan && (
            <div className="plan-summary">
              <strong>{plan.summary}</strong>
              <div className="badges">
                <StatusBadge ok={plan.riskScore <= 30} label={`Risk ${plan.riskScore}`} />
                <StatusBadge ok label={`Confidence ${plan.confidence}`} />
              </div>
              {plan.warnings?.length > 0 && (
                <ul className="warnings">
                  {plan.warnings.map((w: string) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <Output value={planOut} />
        </div>

        <div className="step">
          <h4>3. Review and apply</h4>
          <Field label="Approved by">
            <input value={approvedBy} onChange={(e) => setApprovedBy(e.target.value)} placeholder="your name" />
          </Field>
          <button className="btn btn-primary" onClick={onApply} disabled={!plan}>
            Approve and apply
          </button>
          <Output value={applyOut} />
        </div>
      </div>
    </Card>
  );
}
