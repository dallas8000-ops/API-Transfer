import { useState } from "react";
import { postMigrations } from "../api";
import { Card, Field, Output, StatusBadge } from "../components/ui";

export function Deploy() {
  const [appName, setAppName] = useState("demo-app");
  const [provider, setProvider] = useState("fly");
  const [domain, setDomain] = useState("");
  const [env, setEnv] = useState("stage");
  const [files, setFiles] = useState("package.json\nnext.config.js\npages/index.tsx");
  const [stripe, setStripe] = useState(false);
  const [monitoring, setMonitoring] = useState(true);
  const [backups, setBackups] = useState(true);
  const [requestedBy, setRequestedBy] = useState("ui-user");
  const [result, setResult] = useState<any>(null);
  const [out, setOut] = useState<unknown>("");

  async function onDeploy() {
    try {
      setOut("Deploying… detecting framework and provisioning resources.");
      setResult(null);
      const body = {
        appName,
        targetProvider: provider,
        domain: domain || undefined,
        targetEnvironment: env,
        files: files.split("\n").map((f) => f.trim()).filter(Boolean),
        environment: {},
        secrets: [],
        enableStripe: stripe,
        enableMonitoring: monitoring,
        enableBackups: backups,
        requestedBy: requestedBy || "ui-user",
      };
      const data = await postMigrations("/deploy", body);
      setResult(data.result);
      setOut(data);
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  return (
    <Card title="One-click deploy" hint="AI detects the framework, provisions everything, and returns a live URL.">
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
      <Field label="Project files (one path per line)">
        <textarea className="code" rows={4} spellCheck={false} value={files} onChange={(e) => setFiles(e.target.value)} />
      </Field>
      <Field label="Requested by">
        <input value={requestedBy} onChange={(e) => setRequestedBy(e.target.value)} />
      </Field>
      <div className="toggles">
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
            Framework: <StatusBadge ok label={`${result.framework.framework} · ${result.framework.confidence}%`} />
          </p>
          <p>
            Status: <StatusBadge ok={result.succeeded} label={result.succeeded ? "LIVE" : "NEEDS ATTENTION"} />
          </p>
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
