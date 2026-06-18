import { useEffect, useState } from "react";
import { postMigrations } from "../api";
import { Card, Field, Output, StatusBadge } from "../components/ui";

const REVIEW_PROVIDERS = ["orena", "render", "railway"];

export type ReviewedApp = {
  id: string;
  name: string;
  settings: Record<string, unknown>;
  environmentKeys: string[];
  secretKeys: string[];
};

export function AccountReview({
  demoMode = false,
  onSelectApp,
  bootstrapApps,
  bootstrapProvider,
  bootstrapMessage,
}: {
  demoMode?: boolean;
  onSelectApp?: (provider: string, app: ReviewedApp) => void;
  bootstrapApps?: ReviewedApp[] | null;
  bootstrapProvider?: string;
  bootstrapMessage?: string;
}) {
  const [provider, setProvider] = useState(bootstrapProvider || "railway");
  const [apps, setApps] = useState<ReviewedApp[] | null>(bootstrapApps ?? null);
  const [message, setMessage] = useState(bootstrapMessage || "");
  const [out, setOut] = useState<unknown>("");

  async function onReview(targetProvider = provider) {
    try {
      setOut("Reviewing account...");
      setApps(null);
      const data = await postMigrations("/review", { provider: targetProvider });
      setApps(data.apps || []);
      setMessage(data.message || "");
      setOut(data);
    } catch (e) {
      setApps(null);
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  useEffect(() => {
    if (demoMode) return;
    if (bootstrapApps && bootstrapApps.length > 0) return;
    void onReview(provider);
  }, [demoMode]);

  return (
    <Card
      title="Account review"
      hint="Apps, settings and env key names are pulled from Render/Railway automatically. Secret values stay sealed server-side."
    >
      <div className="row">
        <Field label="Provider">
          <select
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              void onReview(e.target.value);
            }}
          >
            {REVIEW_PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <button className="btn btn-outline" onClick={() => void onReview()}>
        Refresh account inventory
      </button>
      {message && <p className="muted small">{message}</p>}
      {apps && apps.length === 0 && <p className="muted">No services found for this provider.</p>}
      {apps && apps.length > 0 && (
        <div className="provider-grid">
          {apps.map((app) => (
            <div className="provider-tile" key={app.id}>
              <div className="provider-head">
                <strong>{app.name}</strong>
                <StatusBadge ok label={app.id} />
              </div>
              <p className="muted small">
                Env keys: {app.environmentKeys.join(", ") || "none"}
                <br />
                Secret keys: {app.secretKeys.join(", ") || "none"}
              </p>
              {onSelectApp && (
                <button className="btn btn-outline" onClick={() => onSelectApp(provider, app)}>
                  Select and auto-discover
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <Output value={out} />
    </Card>
  );
}
