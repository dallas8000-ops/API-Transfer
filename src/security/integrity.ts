import { createHash } from "crypto";

export function stableStringify(input: unknown): string {
  if (Array.isArray(input)) {
    return `[${input.map(stableStringify).join(",")}]`;
  }

  if (input && typeof input === "object") {
    const entries = Object.entries(input as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b));
    const body = entries.map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`).join(",");
    return `{${body}}`;
  }

  return JSON.stringify(input);
}

export function integrityHash(input: unknown): string {
  return createHash("sha256").update(stableStringify(input)).digest("hex");
}
