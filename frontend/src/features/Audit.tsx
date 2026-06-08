import { useState } from "react";
import { getMigrations } from "../api";
import { Card, Output, StatusBadge } from "../components/ui";

export function Audit() {
  const [entries, setEntries] = useState<any[] | null>(null);
  const [valid, setValid] = useState<any>(null);
  const [out, setOut] = useState<unknown>("");

  async function onRefresh() {
    try {
      setOut("Loading...");
      const data = await getMigrations("/audit");
      setEntries(data.entries);
      setValid(data.valid);
      setOut("");
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  async function onExport() {
    try {
      setOut("Exporting audit package...");
      const data = await getMigrations("/audit/export");
      setOut(data);
    } catch (e) {
      setOut(`Error: ${(e as Error).message}`);
    }
  }

  return (
    <Card title="Audit log" hint="Tamper-evident SHA-256 hash-chain of every privileged action.">
      <div className="toggles">
        <button className="btn btn-outline" onClick={onRefresh}>
          Refresh audit
        </button>
        <button className="btn btn-outline" onClick={onExport}>
          Export audit
        </button>
        {valid && <StatusBadge ok={valid.valid} label={valid.valid ? "Chain valid" : `Broken at ${valid.brokenAt}`} />}
      </div>
      {entries && (
        <table className="audit-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Action</th>
              <th>Actor</th>
              <th>Reference</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.sequence}>
                <td>{e.sequence}</td>
                <td>{e.action}</td>
                <td className="mono">{e.actor}</td>
                <td>{e.reference}</td>
                <td className="muted">{new Date(e.createdAt).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Output value={out} />
    </Card>
  );
}
