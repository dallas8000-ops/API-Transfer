import { useEffect, useState } from "react";
import { postMigrations } from "../api";
import { Card, Field, Output, StatusBadge } from "../components/ui";
import type { ReviewedApp } from "./AccountReview";

type BackupResult = {
  message: string;
  serviceName: string;
  serviceId: string;
  keyCount: number;
  secretKeyCount: number;
  variableKeys: string[];
  secretKeys: string[];
  backupPath?: string;
  backedUpAt?: string;
  backup?: {
    serviceName: string;
    serviceId: string;
    projectId: string;
    environmentId: string;
    backedUpAt: string;
    variables: Record<string, string>;
  };
};

function downloadBackupJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function RailwayEnvBackup({
  demoMode = false,
  railwayApps,
  selectedApp,
}: {
  demoMode?: boolean;
  railwayApps?: ReviewedApp[] | null;
  selectedApp?: { provider: string; app: ReviewedApp } | null;
}) {
  const apps = railwayApps ?? [];
  const [serviceId, setServiceId] = useState("");
  const [serviceName, setServiceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BackupResult | null>(null);
  const [out, setOut] = useState<unknown>("");

  useEffect(() => {
    if (!selectedApp || selectedApp.provider !== "railway") return;
    setServiceId(selectedApp.app.id);
    setServiceName(selectedApp.app.name);
  }, [selectedApp]);

  useEffect(() => {
    if (serviceId || apps.length === 0) return;
    setServiceId(apps[0].id);
    setServiceName(apps[0].name);
  }, [apps, serviceId]);

  function onServiceChange(id: string) {
    setServiceId(id);
    const match = apps.find((app) => app.id === id);
    setServiceName(match?.name || id);
    setResult(null);
  }

  async function onBackup() {
    if (!serviceId) {
      setOut("Select a Railway service first.");
      return;
    }
    try {
      setBusy(true);
      setOut("Fetching variables from Railway...");
      setResult(null);
      const data = await postMigrations("/env/backup/railway", {
        serviceId,
        serviceName,
        saveToDisk: true,
      });
      setResult(data);
      setOut(data);
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  function onDownload() {
    if (!result?.backup) return;
    const stamp = result.backedUpAt || "backup";
    const safeName = (result.serviceName || "railway-service").replace(/[^\w.-]+/g, "-");
    downloadBackupJson(`${safeName}-${stamp}.json`, result.backup);
  }

  if (demoMode) {
    return (
      <Card
        title="Railway env backup"
        hint="Export all variables from a Railway service before transfer or deploy."
      >
        <p className="muted small">Switch to Live mode to back up Railway variables.</p>
      </Card>
    );
  }

  return (
    <Card
      title="Railway env backup"
      hint="One-click snapshot of every variable on a Railway service — saved server-side and downloadable as JSON."
    >
      {apps.length === 0 ? (
        <p className="muted small">
          No Railway services in inventory yet. Refresh account review above, or paste a service ID below.
        </p>
      ) : (
        <Field label="Railway service">
          <select value={serviceId} onChange={(e) => onServiceChange(e.target.value)}>
            {apps.map((app) => (
              <option key={app.id} value={app.id}>
                {app.name} ({app.secretKeys.length} secret key{app.secretKeys.length === 1 ? "" : "s"})
              </option>
            ))}
          </select>
        </Field>
      )}
      <div className="row">
        <Field label="Service ID (override)">
          <input
            value={serviceId}
            onChange={(e) => {
              setServiceId(e.target.value);
              setResult(null);
            }}
            placeholder="Railway service UUID"
          />
        </Field>
        <Field label="Display name">
          <input value={serviceName} onChange={(e) => setServiceName(e.target.value)} placeholder="stripe-installer" />
        </Field>
      </div>
      <div className="toggles">
        <button className="btn btn-primary" disabled={busy || !serviceId} onClick={() => void onBackup()}>
          {busy ? "Backing up…" : "Export Railway env backup"}
        </button>
        {result?.backup && (
          <button className="btn btn-outline" onClick={onDownload}>
            Download JSON
          </button>
        )}
      </div>
      {result && (
        <div className="deploy-live">
          <p>
            Status: <StatusBadge ok label={`${result.keyCount} vars · ${result.secretKeyCount} secrets`} />
          </p>
          {result.backupPath && (
            <p className="muted small">
              Server copy: <code>{result.backupPath}</code>
            </p>
          )}
          {result.secretKeys.length > 0 && (
            <p className="muted small">Secret keys: {result.secretKeys.join(", ")}</p>
          )}
        </div>
      )}
      <Output value={out} />
    </Card>
  );
}
