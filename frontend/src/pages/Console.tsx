import { useState } from "react";
import { getApiKey, setApiKey } from "../api";
import { Card, Field } from "../components/ui";
import { DiscoverPlanApply } from "../features/DiscoverPlanApply";
import { Deploy } from "../features/Deploy";
import { Diagnose } from "../features/Diagnose";
import { Audit } from "../features/Audit";

export function Console() {
  const [key, setKey] = useState(getApiKey());

  return (
    <div className="console">
      <div className="console-head">
        <h1>Console</h1>
        <p className="muted">
          Run discovery, planning, deployments and diagnostics. Privileged actions are gated by
          your API key role (viewer · operator · admin).
        </p>
      </div>

      <Card title="Access" hint="Optional in local dev. Required for operator/admin actions in production.">
        <Field label="API Key (x-api-key)">
          <input
            type="password"
            autoComplete="off"
            placeholder="Leave blank in local dev"
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
              setApiKey(e.target.value);
            }}
          />
        </Field>
      </Card>

      <DiscoverPlanApply />
      <Deploy />
      <Diagnose />
      <Audit />
    </div>
  );
}
