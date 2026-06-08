import { useState } from "react";
import { postMigrations } from "../api";
import { Card, Field, Output, StatusBadge } from "../components/ui";

export type ImportedProject = {
  appName: string;
  repoUrl: string;
  branch: string;
  files: string[];
  packageJson: Record<string, unknown> | null;
  environment: Record<string, string>;
  secrets: { key: string; value: string }[];
};

export function GitHubImport({ onImported }: { onImported: (project: ImportedProject) => void }) {
  const [repoUrl, setRepoUrl] = useState("https://github.com/owner/repo");
  const [branch, setBranch] = useState("");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<any>(null);
  const [out, setOut] = useState<unknown>("");

  async function onImport() {
    try {
      setOut("Importing repository...");
      setResult(null);
      const data = await postMigrations("/github/import", {
        repoUrl,
        branch,
        accessToken: token,
      });
      setResult(data);
      onImported(data.project);
      setOut(data);
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  return (
    <Card title="GitHub import" hint="Import a repo tree, detect the framework, and prefill diagnostics/deployment inputs.">
      <div className="row">
        <Field label="GitHub repository URL">
          <input value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/org/app" />
        </Field>
        <Field label="Branch (optional)">
          <input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="Default branch" />
        </Field>
      </div>
      <Field label="GitHub token for private repos (optional)">
        <input
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="Not stored or returned"
        />
      </Field>
      <button className="btn btn-primary" onClick={onImport}>
        Import repo
      </button>
      {result && (
        <div className="deploy-live">
          <p>
            Repo: <strong>{result.repository.fullName}</strong>
          </p>
          <p>
            Framework:{" "}
            <StatusBadge ok={result.framework.confidence >= 50} label={`${result.framework.framework} | ${result.framework.confidence}%`} />
          </p>
          <p>
            Files: <strong>{result.limits.fileCount}</strong>{" "}
            <StatusBadge ok={result.limits.packageJsonFound} label={result.limits.packageJsonFound ? "package.json found" : "no package.json"} />
          </p>
        </div>
      )}
      <Output value={out} />
    </Card>
  );
}
