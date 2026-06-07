import type { ReactNode } from "react";

export function Card({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="console-card">
      <header>
        <h3>{title}</h3>
        {hint && <p className="hint">{hint}</p>}
      </header>
      {children}
    </section>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function Output({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return null;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return <pre className="output">{text}</pre>;
}

export function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return <span className={`badge ${ok ? "ok" : "warn"}`}>{label}</span>;
}
