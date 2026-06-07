const SENSITIVE_KEYS = ["secret", "token", "password", "apiKey", "authorization", "privateKey"];

function isSensitiveKey(key: string): boolean {
  return SENSITIVE_KEYS.some((needle) => key.toLowerCase().includes(needle.toLowerCase()));
}

export function redactSensitiveValues(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => redactSensitiveValues(item));
  }

  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      out[key] = isSensitiveKey(key) ? "[REDACTED]" : redactSensitiveValues(child);
    }
    return out;
  }

  return value;
}
