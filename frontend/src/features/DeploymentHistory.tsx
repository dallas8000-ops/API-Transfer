import { useState } from "react";
import { getMigrations, postMigrations } from "../api";
import { Card, Output, StatusBadge } from "../components/ui";

export function DeploymentHistory() {
  const [runs, setRuns] = useState<any[] | null>(null);
  const [out, setOut] = useState<unknown>("");

  async function onRefresh() {
    try {
      setOut("Loading deployment history...");
      const data = await getMigrations("/deploy/history");
      setRuns(data.runs);
      setOut("");
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  async function onRefreshStatus(deploymentId: string) {
    try {
      setOut("Refreshing deployment status...");
      const data = await postMigrations(`/deploy/status/${deploymentId}`, {});
      setRuns((current) =>
        current ? current.map((run) => (run.deploymentId === deploymentId ? data.run : run)) : current
      );
      setOut(data);
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  return (
    <Card title="Deployment history" hint="Client-visible record of recent deploys, live status and output URLs.">
      <button className="btn btn-outline" onClick={onRefresh}>
        Refresh history
      </button>
      {runs && runs.length === 0 && <p className="muted">No deployments have been recorded yet.</p>}
      {runs && runs.length > 0 && (
        <table className="audit-table">
          <thead>
            <tr>
              <th>App</th>
              <th>Provider</th>
              <th>Status</th>
              <th>Mode</th>
              <th>Provider IDs</th>
              <th>URL</th>
              <th>Checked</th>
              <th>When</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.deploymentId}>
                <td>{run.appName}</td>
                <td>{run.targetProvider}</td>
                <td>
                  <StatusBadge ok={run.status === "live" || run.status === "simulated"} label={run.status || (run.succeeded ? "succeeded" : "attention")} />
                </td>
                <td>
                  <StatusBadge ok={run.live} label={run.live ? "Live" : "Simulated"} />
                </td>
                <td className="mono small">
                  {run.providerServiceId || "none"}
                  {run.providerDeployId ? ` / ${run.providerDeployId}` : ""}
                </td>
                <td>
                  {run.liveUrl ? (
                    <a href={run.liveUrl} target="_blank" rel="noopener noreferrer">
                      Open
                    </a>
                  ) : (
                    <span className="muted">None</span>
                  )}
                </td>
                <td className="muted">{run.lastCheckedAt ? new Date(run.lastCheckedAt).toLocaleString() : "Not checked"}</td>
                <td className="muted">{new Date(run.createdAt).toLocaleString()}</td>
                <td>
                  <button className="btn btn-outline btn-sm" onClick={() => onRefreshStatus(run.deploymentId)}>
                    Refresh status
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Output value={out} />
    </Card>
  );
}
