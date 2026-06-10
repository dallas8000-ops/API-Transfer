import { useState } from "react";
import { getMigrations } from "../api";
import { Card, Output, StatusBadge } from "../components/ui";

export function ProviderReadiness() {
  const [providers, setProviders] = useState<any[] | null>(null);
  const [out, setOut] = useState<unknown>("");

  async function onRefresh() {
    try {
      setOut("Checking providers...");
      const data = await getMigrations("/providers/status");
      setProviders(data.providers);
      setOut("");
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  return (
    <Card title="Provider readiness" hint="Demo means simulated or planning-only — those features still work. Live means real API calls when credentials are configured in .env.">
      <button className="btn btn-outline" onClick={onRefresh}>
        Check providers
      </button>
      {providers && (
        <div className="provider-grid">
          {providers.map((p) => (
            <div className="provider-tile" key={p.provider}>
              <div className="provider-head">
                <strong>{p.provider}</strong>
                <StatusBadge ok={p.liveEnabled} label={p.liveEnabled ? "Live" : "Demo"} />
              </div>
              <p className="muted small">{p.message}</p>
              <div className="capabilities">
                {p.capabilities.map((cap: string) => (
                  <span key={cap}>{cap}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      <Output value={out} />
    </Card>
  );
}
