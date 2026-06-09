import { useState } from "react";
import { postMigrations } from "../api";
import { Card, Field, Output, StatusBadge } from "../components/ui";

const REVIEW_PROVIDERS = ["render", "railway"];

export type ReviewedApp = {
  id: string;
  name: string;
  settings: Record<string, unknown>;
  environmentKeys: string[];
  secretKeys: string[];
};

export function AccountReview({
  onSelectApp,
}: {
  onSelectApp?: (provider: string, app: ReviewedApp) => void;
}) {
  const [provider, setProvider] = useState("render");
  const [apps, setApps] = useState<ReviewedApp[] | null>(null);
  const [message, setMessage] = useState("");
  const [out, setOut] = useState<unknown>("");

  async function onReview() {
    try {
      setOut("Reviewing account...");
      setApps(null);
      const data = await postMigrations("/review", { provider });
      setApps(data.apps || []);
      setMessage(data.message || "");
      setOut(data);
    } catch (e) {
      setApps(null);
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  return (
    <Card
      title="Account review"
      hint="Inspect Render or Railway apps, settings and env key names. Secret values stay sealed server-side and are never returned."
    >
      <div className="row">
        <Field label="Provider">
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            {REVIEW_PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <button className="btn btn-outline" onClick={onReview}>
        Review account
      </button>
      {message && <p className="muted small">{message}</p>}
      {apps && (
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
                  Use for migration
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
