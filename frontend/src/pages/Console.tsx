import { useEffect, useState } from "react";
import { getAccount, getAccountEmail, getApiKey, setAccountEmail, setApiKey } from "../api";
import { Audit } from "../features/Audit";
import { Deploy } from "../features/Deploy";
import { DeploymentHistory } from "../features/DeploymentHistory";
import { Diagnose } from "../features/Diagnose";
import { AccountReview } from "../features/AccountReview";
import { DiscoverPlanApply } from "../features/DiscoverPlanApply";
import type { ReviewedApp } from "../features/AccountReview";
import { GitHubImport, type ImportedProject } from "../features/GitHubImport";
import { ProviderReadiness } from "../features/ProviderReadiness";
import { Card, Field, Output, StatusBadge } from "../components/ui";

export function Console() {
  const [key, setKey] = useState(getApiKey());
  const [email, setEmail] = useState(getAccountEmail());
  const [account, setAccount] = useState<any>(null);
  const [accountOut, setAccountOut] = useState<unknown>("");
  const [importedProject, setImportedProject] = useState<ImportedProject | null>(null);
  const [selectedApp, setSelectedApp] = useState<{ provider: string; app: ReviewedApp } | null>(null);
  const [discoveryId, setDiscoveryId] = useState("");

  async function refreshAccount() {
    try {
      setAccountOut("Loading workspace...");
      const data = await getAccount();
      setAccount(data);
      setAccountOut("");
    } catch (e) {
      setAccountOut(`Error: ${(e as Error).message}`);
    }
  }

  useEffect(() => {
    refreshAccount();
  }, []);

  return (
    <div className="console">
      <div className="console-head">
        <h1>Migration Console</h1>
        <p className="muted">
          Diagnose, plan, deploy and audit client migrations with explicit live-provider status,
          workspace usage limits and secret-safe outputs.
        </p>
      </div>

      <Card title="Workspace access" hint="Use account email for billing limits and API key for privileged actions.">
        <div className="row">
          <Field label="Account email">
            <input
              type="email"
              autoComplete="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setAccountEmail(e.target.value);
              }}
              onBlur={refreshAccount}
            />
          </Field>
          <Field label="API key (x-api-key)">
            <input
              type="password"
              autoComplete="off"
              placeholder="Required for operator/admin actions in production"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
                setApiKey(e.target.value);
              }}
            />
          </Field>
        </div>
        {account && (
          <div className="account-strip">
            <div>
              <span className="muted small">Workspace</span>
              <strong>{account.workspace.name}</strong>
            </div>
            <div>
              <span className="muted small">Plan</span>
              <StatusBadge ok={account.planSlug !== "free"} label={account.plan.name} />
            </div>
            <div>
              <span className="muted small">Usage</span>
              <strong>
                {account.usage.migrationsThisMonth} migrations / {account.usage.liveDeploymentsThisMonth} live deploys
              </strong>
            </div>
          </div>
        )}
        <Output value={accountOut} />
      </Card>

      <GitHubImport onImported={setImportedProject} />
      <ProviderReadiness />
      <AccountReview onSelectApp={(provider, app) => setSelectedApp({ provider, app })} />
      <DiscoverPlanApply selectedApp={selectedApp} onDiscovery={setDiscoveryId} />
      <Deploy importedProject={importedProject} discoveryId={discoveryId} />
      <Diagnose importedProject={importedProject} />
      <DeploymentHistory />
      <Audit />
    </div>
  );
}
