import { useCallback, useEffect, useState } from "react";
import { useDemoMode } from "../DemoModeContext";
import { getAccount, getAccountEmail, getApiKey, getConsoleBootstrap, postMigrations, setAccountEmail, setApiKey } from "../api";
import { Audit } from "../features/Audit";
import { Deploy } from "../features/Deploy";
import { RailwayEnvBackup } from "../features/RailwayEnvBackup";
import { DeploymentHistory } from "../features/DeploymentHistory";
import { Diagnose } from "../features/Diagnose";
import { AccountReview } from "../features/AccountReview";
import { DiscoverPlanApply } from "../features/DiscoverPlanApply";
import { TransferControl } from "../features/TransferControl";
import type { ReviewedApp } from "../features/AccountReview";
import { GitHubImport, type ImportedProject } from "../features/GitHubImport";
import { ProviderReadiness } from "../features/ProviderReadiness";
import { PlatformSetup } from "../features/PlatformSetup";
import { Card, Field, Output, StatusBadge } from "../components/ui";

export function Console() {
  const { demoMode, refreshAllowToggle } = useDemoMode();
  const [key, setKey] = useState(getApiKey());
  const [email, setEmail] = useState(getAccountEmail());
  const [account, setAccount] = useState<any>(null);
  const [accountOut, setAccountOut] = useState<unknown>("");
  const [importedProject, setImportedProject] = useState<ImportedProject | null>(null);
  const [selectedApp, setSelectedApp] = useState<{ provider: string; app: ReviewedApp } | null>(null);
  const [discoveryId, setDiscoveryId] = useState("");
  const [bootstrapProviders, setBootstrapProviders] = useState<any[] | null>(null);
  const [bootstrapServerConfig, setBootstrapServerConfig] = useState<Record<string, any> | null>(null);
  const [railwayApps, setRailwayApps] = useState<ReviewedApp[] | null>(null);
  const [railwayMessage, setRailwayMessage] = useState("");
  const [bootstrapOut, setBootstrapOut] = useState<unknown>("");
  const [platformSetup, setPlatformSetup] = useState<any>(null);

  const refreshAccount = useCallback(async () => {
    try {
      setAccountOut("Loading workspace...");
      const data = await getAccount();
      setAccount(data);
      setAccountOut("");
    } catch (e) {
      setAccountOut(`Error: ${(e as Error).message}`);
    }
  }, []);

  const loadBootstrap = useCallback(async () => {
    try {
      setBootstrapOut("Pulling provider inventories...");
      const data = await getConsoleBootstrap();
      refreshAllowToggle(Boolean(data.allowDemoToggle));
      setAccount(data.account);
      setBootstrapProviders(data.providers);
      setBootstrapServerConfig(data.serverConfig);
      setPlatformSetup(data.platformSetup ?? null);
      const railway = data.accountInventories?.railway;
      if (railway?.apps) {
        setRailwayApps(railway.apps);
        setRailwayMessage(railway.message || "");
      }
      setBootstrapOut("");
    } catch (e) {
      setBootstrapOut(`Error: ${(e as Error).message}`);
    }
  }, [refreshAllowToggle]);

  const selectApp = useCallback(async (provider: string, app: ReviewedApp) => {
    setSelectedApp({ provider, app });
    try {
      setBootstrapOut(`Discovering ${app.name}...`);
      const data = await postMigrations("/discover", { provider, appIdentifier: app.id });
      setDiscoveryId(data.discoveryId || "");
      setBootstrapOut(`Selected ${app.name} · discovery ${data.discoveryId || "ready"}`);
    } catch (e) {
      setBootstrapOut(`Discover failed: ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    void refreshAccount();
    void loadBootstrap();
  }, [demoMode, loadBootstrap, refreshAccount]);

  return (
    <div className="console">
      <div className="console-head">
        <h1>Migration Console</h1>
        <p className="muted">
          {demoMode
            ? "Design mode — explore the workflow with safe simulation. Use the Mode switch in the header for Live."
            : "Live mode — provider inventories and app metadata are pulled automatically. Select a service to discover, plan, and deploy."}
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
              onBlur={() => {
                void refreshAccount();
                void loadBootstrap();
              }}
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
            {account.license?.registeredDomain && (
              <div>
                <span className="muted small">Licensed domain</span>
                <strong>{account.license.registeredDomain}</strong>
              </div>
            )}
          </div>
        )}
        <p className="muted small">
          Local dev: leave <strong>API key empty</strong> and RBAC keys empty in <code>.env</code>. If you see
          permission errors, restart Django and hard-refresh — or clear any value in the API key field above.
        </p>
        <Output value={accountOut} />
        <Output value={bootstrapOut} />
      </Card>

      <ProviderReadiness
        demoMode={demoMode}
        bootstrapProviders={bootstrapProviders}
        bootstrapServerConfig={bootstrapServerConfig}
      />
      {!demoMode && <GitHubImport onImported={setImportedProject} />}
      <AccountReview
        demoMode={demoMode}
        bootstrapApps={demoMode ? null : railwayApps}
        bootstrapProvider="railway"
        bootstrapMessage={demoMode ? "Demo mode — connect via /console for live Railway inventory." : railwayMessage}
        onSelectApp={demoMode ? undefined : (provider, app) => void selectApp(provider, app)}
      />
      <DiscoverPlanApply demoMode={demoMode} selectedApp={selectedApp} discoveryId={discoveryId} onDiscovery={setDiscoveryId} />
      {!demoMode && <TransferControl importedProject={importedProject} selectedApp={selectedApp} />}
      {!demoMode && (
        <RailwayEnvBackup demoMode={demoMode} railwayApps={railwayApps} selectedApp={selectedApp} />
      )}
      <Deploy
        demoMode={demoMode}
        importedProject={importedProject}
        discoveryId={discoveryId}
        selectedApp={selectedApp}
        registeredDomain={account?.license?.registeredDomain}
      />
      <PlatformSetup demoMode={demoMode} bootstrapSetup={platformSetup} onConfigChanged={loadBootstrap} />
      <Diagnose demoMode={demoMode} importedProject={importedProject} selectedApp={selectedApp} />
      <DeploymentHistory />
      <Audit />
    </div>
  );
}
