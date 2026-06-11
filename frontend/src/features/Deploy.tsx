import { useEffect, useState } from "react";
import { postMigrations } from "../api";
import { reviewedAppBranch, reviewedAppRepoUrl } from "../reviewedApp";
import { Card, Field, Output, StatusBadge } from "../components/ui";
import type { ReviewedApp } from "./AccountReview";
import type { ImportedProject } from "./GitHubImport";

export function Deploy({
  demoMode = false,
  importedProject,
  discoveryId,
  selectedApp,
  registeredDomain,
}: {
  demoMode?: boolean;
  importedProject?: ImportedProject | null;
  discoveryId?: string;
  selectedApp?: { provider: string; app: ReviewedApp } | null;
  registeredDomain?: string;
}) {
  const [appName, setAppName] = useState(
    importedProject?.appName || selectedApp?.app.name || (demoMode ? "demo-app" : ""),
  );
  const [provider, setProvider] = useState(selectedApp?.provider || "railway");
  const [repoUrl, setRepoUrl] = useState(importedProject?.repoUrl || "");
  const [branch, setBranch] = useState(importedProject?.branch || "");
  const [domain, setDomain] = useState(registeredDomain || "");
  const [env, setEnv] = useState("stage");
  const [files, setFiles] = useState(importedProject?.files?.join("\n") || "package.json\nnext.config.js\npages/index.tsx");
  const [stripe, setStripe] = useState(false);
  const [monitoring, setMonitoring] = useState(true);
  const [backups, setBackups] = useState(true);
  const [requestedBy, setRequestedBy] = useState("ui-user");
  const [result, setResult] = useState<any>(null);
  const [out, setOut] = useState<unknown>("");

  useEffect(() => {
    if (!selectedApp) return;
    setAppName(selectedApp.app.name);
    setProvider(selectedApp.provider);
    const repo = reviewedAppRepoUrl(selectedApp.app);
    if (repo) setRepoUrl(repo);
    const appBranch = reviewedAppBranch(selectedApp.app);
    if (appBranch) setBranch(appBranch);
  }, [selectedApp]);

  useEffect(() => {
    if (registeredDomain) setDomain(registeredDomain);
  }, [registeredDomain]);

  function useImportedProject() {
    if (!importedProject) return;
    setAppName(importedProject.appName);
    setRepoUrl(importedProject.repoUrl);
    setBranch(importedProject.branch);
    setFiles(importedProject.files.join("\n"));
  }

  async function onDeploy() {
    try {
      setOut("Deploying... detecting framework and provisioning resources.");
      setResult(null);
      const body = {
        appName,
        targetProvider: provider,
        repoUrl,
        branch,
        domain: domain || undefined,
        targetEnvironment: env,
        files: files
          .split("\n")
          .map((f) => f.trim())
          .filter(Boolean),
        packageJson: importedProject?.packageJson || undefined,
        environment: importedProject?.environment || {},
        secrets: [],
        enableStripe: stripe,
        enableMonitoring: monitoring,
        enableBackups: backups,
        requestedBy: requestedBy || "ui-user",
        discoveryId: discoveryId || undefined,
      };
      const data = await postMigrations("/deploy", body);
      setResult(data.result);
      setOut(data);
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  const liveSummary = result?.liveExecution;

  return (
    <Card title="One-click deploy" hint="Detect the framework, run provider stages and label live versus simulated work.">
      <div className="row">
        <Field label="App name">
          <input value={appName} onChange={(e) => setAppName(e.target.value)} />
        </Field>
        <Field label="Target provider">
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="render">render</option>
            <option value="railway">railway</option>
            <option value="fly">fly</option>
          </select>
        </Field>
      </div>
      <div className="row">
        <Field label="Custom domain (optional)">
          <input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="example.com" />
        </Field>
        <Field label="Environment">
          <select value={env} onChange={(e) => setEnv(e.target.value)}>
            <option value="dev">dev</option>
            <option value="stage">stage</option>
            <option value="prod">prod</option>
          </select>
        </Field>
      </div>
      <div className="row">
        <Field label="Repository URL for live Render/Railway deploys">
          <input value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/org/app" />
        </Field>
        <Field label="Branch">
          <input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" />
        </Field>
      </div>
      <Field label="Project files (one path per line)">
        <textarea className="code" rows={4} spellCheck={false} value={files} onChange={(e) => setFiles(e.target.value)} />
      </Field>
      <Field label="Requested by">
        <input value={requestedBy} onChange={(e) => setRequestedBy(e.target.value)} />
      </Field>
      <div className="toggles">
        {importedProject && (
          <button className="btn btn-outline" onClick={useImportedProject}>
            Use GitHub import
          </button>
        )}
        <label className="inline">
          <input type="checkbox" checked={stripe} onChange={(e) => setStripe(e.target.checked)} /> Stripe
        </label>
        <label className="inline">
          <input type="checkbox" checked={monitoring} onChange={(e) => setMonitoring(e.target.checked)} /> Monitoring
        </label>
        <label className="inline">
          <input type="checkbox" checked={backups} onChange={(e) => setBackups(e.target.checked)} /> Backups
        </label>
      </div>
      <button className="btn btn-primary" onClick={onDeploy}>
        Deploy
      </button>

      {result && (
        <div className="deploy-live">
          <p>
            Framework: <StatusBadge ok label={`${result.framework.framework} | ${result.framework.confidence}%`} />
          </p>
          <p>
            Status: <StatusBadge ok={result.succeeded} label={result.succeeded ? "Succeeded" : "Needs attention"} />
          </p>
          {liveSummary && (
            <p>
              Execution:{" "}
              <StatusBadge ok={liveSummary.fullyLive} label={liveSummary.fullyLive ? "Fully live" : "Some simulation"} />
              <span className="muted small"> {liveSummary.message}</span>
            </p>
          )}
          {result.liveUrl && (
            <p>
              Live URL:{" "}
              <a href={result.liveUrl} target="_blank" rel="noopener noreferrer">
                {result.liveUrl}
              </a>
            </p>
          )}
        </div>
      )}
      <Output value={out} />
    </Card>
  );
}
