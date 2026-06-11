import { useEffect, useState } from "react";
import { getMigrations } from "../api";
import { Card, Output, StatusBadge } from "../components/ui";

type ProviderRow = {
  provider: string;
  liveEnabled: boolean;
  message: string;
  capabilities: string[];
};

type ServerConfig = Record<string, { configured: boolean; missing: string[]; projectId?: string | null }>;

export function ProviderReadiness({
  demoMode = false,
  bootstrapProviders,
  bootstrapServerConfig,
}: {
  demoMode?: boolean;
  bootstrapProviders?: ProviderRow[] | null;
  bootstrapServerConfig?: ServerConfig | null;
}) {
  const [providers, setProviders] = useState<ProviderRow[] | null>(bootstrapProviders ?? null);
  const [serverConfig, setServerConfig] = useState<ServerConfig | null>(bootstrapServerConfig ?? null);
  const [out, setOut] = useState<unknown>("");

  async function onRefresh() {
    try {
      setOut("Checking providers...");
      const data = await getMigrations("/providers/status");
      setProviders(data.providers);
      setServerConfig(data.serverConfig || null);
      setOut("");
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  useEffect(() => {
    if (!bootstrapProviders) {
      void onRefresh();
    }
  }, []);

  const configEntries = serverConfig ? Object.entries(serverConfig) : [];
  const missingAll = configEntries.flatMap(([name, cfg]) =>
    cfg.missing.map((key) => `${name}: ${key}`),
  );

  return (
    <Card
      title="Provider readiness"
      hint={
        demoMode
          ? "Demo mode uses safe simulation. Open /console for live provider status."
          : "Live providers are queried automatically when server credentials are configured in .env."
      }
    >
      {demoMode && (
        <p className="notice">Demo mode — provider tiles show simulation status only.</p>
      )}
      {!demoMode && missingAll.length > 0 && (
        <p className="notice">
          Server still needs: {missingAll.join(", ")}. Add these to API Transfer&apos;s <code>.env</code> and restart
          Django — the console cannot invent provider credentials.
        </p>
      )}
      {serverConfig?.railway?.projectId && (
        <p className="muted small">Railway project: {serverConfig.railway.projectId}</p>
      )}
      <button className="btn btn-outline" onClick={onRefresh}>
        Refresh providers
      </button>
      {providers && (
        <div className="provider-grid">
          {providers.map((p) => (
            <div className="provider-tile" key={p.provider}>
              <div className="provider-head">
                <strong>{p.provider}</strong>
                <StatusBadge
                  ok={p.liveEnabled}
                  label={p.liveEnabled ? "Live" : demoMode ? "Demo" : "Not configured"}
                />
              </div>
              <p className="muted small">{p.message}</p>
              <div className="capabilities">
                {p.capabilities.map((cap) => (
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
