// Lightweight typed API client for the API Transfer backend.
// In dev, Vite proxies these paths to Django; in production Django serves both
// the SPA and the API from the same origin.

const MIGRATIONS_BASE = "/api/migrations";
const BILLING_BASE = "/api/billing";

let apiKey = "";

export function setApiKey(key: string): void {
  apiKey = key.trim();
}

export function getApiKey(): string {
  return apiKey;
}

function headers(json = true): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  if (apiKey) h["x-api-key"] = apiKey;
  return h;
}

async function parse(response: Response): Promise<any> {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || data.detail || `Request failed (${response.status})`);
  }
  return data;
}

export async function postMigrations(path: string, body: unknown): Promise<any> {
  const res = await fetch(`${MIGRATIONS_BASE}${path}`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  return parse(res);
}

export async function getMigrations(path: string): Promise<any> {
  const res = await fetch(`${MIGRATIONS_BASE}${path}`, { headers: headers(false) });
  return parse(res);
}

// --- Billing ---------------------------------------------------------------

export interface Plan {
  slug: string;
  name: string;
  description: string;
  price: number;
  priceCents: number;
  interval: string;
  currency: string;
  features: string[];
  limits: Record<string, number | null>;
  cta: string;
  highlighted: boolean;
  purchasable: boolean;
}

export interface PlansResponse {
  plans: Plan[];
  publishableKey: string;
  billingEnabled: boolean;
}

export async function getPlans(): Promise<PlansResponse> {
  const res = await fetch(`${BILLING_BASE}/plans`);
  return parse(res);
}

export async function startCheckout(email: string, planSlug: string): Promise<{ url: string; sessionId: string }> {
  const res = await fetch(`${BILLING_BASE}/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, planSlug }),
  });
  return parse(res);
}

export async function getSubscription(email: string): Promise<any> {
  const res = await fetch(`${BILLING_BASE}/subscription?email=${encodeURIComponent(email)}`);
  return parse(res);
}
