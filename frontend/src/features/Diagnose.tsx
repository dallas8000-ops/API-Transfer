import { useState } from "react";
import { postMigrations } from "../api";
import { Card, Field, Output } from "../components/ui";
import type { ImportedProject } from "./GitHubImport";

function parseEnvVars(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const idx = trimmed.indexOf("=");
    if (idx === -1) continue;
    out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim();
  }
  return out;
}

const SEV_ORDER = ["critical", "high", "medium", "low", "info"];

function Report({ report }: { report: any }) {
  if (!report) return null;
  const s = report.summary;
  return (
    <div className="report">
      <div className="report-head">
        <span className={`health health-${s.healthScore >= 80 ? "ok" : s.healthScore >= 50 ? "warn" : "bad"}`}>
          Health {s.healthScore}
        </span>
        <span className="muted">
          {s.total} issue(s) | {s.autoFixable} auto-fixable
        </span>
        <span className="sev-line">
          {SEV_ORDER.map((sev) =>
            s.bySeverity[sev] ? (
              <span key={sev} className={`sev sev-${sev}`}>
                {sev}: {s.bySeverity[sev]}
              </span>
            ) : null
          )}
        </span>
      </div>
      <ul className="issues">
        {report.issues.map((i: any) => (
          <li key={i.id} className={`issue sev-border-${i.severity}`}>
            <div className="issue-title">
              <span className={`sev sev-${i.severity}`}>{i.severity}</span>
              <strong>{i.title}</strong>
              {i.autoFixable && <span className="badge ok">auto-fixable</span>}
            </div>
            <p className="muted">{i.detail}</p>
            {i.recommendation && <p className="reco">Recommended: {i.recommendation}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Diagnose({ importedProject }: { importedProject?: ImportedProject | null }) {
  const [appName, setAppName] = useState(importedProject?.appName || "demo-app");
  const [provider, setProvider] = useState("fly");
  const [domain, setDomain] = useState("");
  const [env, setEnv] = useState("prod");
  const [files, setFiles] = useState(importedProject?.files?.join("\n") || "package.json\nserver.js");
  const [envVars, setEnvVars] = useState("API_KEY=sk_live_abc123\nNODE_ENV=development");
  const [report, setReport] = useState<any>(null);
  const [out, setOut] = useState<unknown>("");
  const [autoFixable, setAutoFixable] = useState(0);

  function useImportedProject() {
    if (!importedProject) return;
    setAppName(importedProject.appName);
    setFiles(importedProject.files.join("\n"));
  }

  function buildProject() {
    return {
      appName,
      targetProvider: provider,
      domain: domain || undefined,
      targetEnvironment: env,
      files: files
        .split("\n")
        .map((f) => f.trim())
        .filter(Boolean),
      environment: parseEnvVars(envVars),
      secrets: [],
      requestedBy: "ui-user",
    };
  }

  async function onDiagnose() {
    try {
      setOut("Analyzing project settings...");
      const data = await postMigrations("/diagnose", buildProject());
      setReport(data.report);
      setAutoFixable(data.report.summary.autoFixable);
      setOut(data);
    } catch (e) {
      setReport(null);
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  async function onAutoFix() {
    try {
      setOut("Applying safe auto-fixes...");
      const data = await postMigrations("/diagnose/fix", { project: buildProject() });
      if (data.result?.residualReport) {
        setReport(data.result.residualReport);
        setAutoFixable(data.result.residualReport.summary.autoFixable);
      }
      setOut(data);
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  return (
    <Card title="Diagnose and auto-fix" hint="Surface misconfigurations by severity and apply safe fixes automatically.">
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
        <textarea className="code" rows={3} spellCheck={false} value={files} onChange={(e) => setFiles(e.target.value)} />
      </Field>
      <Field label="Environment variables (KEY=value per line)">
        <textarea className="code" rows={3} spellCheck={false} value={envVars} onChange={(e) => setEnvVars(e.target.value)} />
      </Field>
      <div className="toggles">
        {importedProject && (
          <button className="btn btn-outline" onClick={useImportedProject}>
            Use GitHub import
          </button>
        )}
        <button className="btn btn-outline" onClick={onDiagnose}>
          Diagnose
        </button>
        <button className="btn btn-primary" onClick={onAutoFix} disabled={autoFixable === 0}>
          Auto-fix all
        </button>
      </div>
      <Report report={report} />
      <Output value={out} />
    </Card>
  );
}
