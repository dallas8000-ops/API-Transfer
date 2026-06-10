// Lightweight typed API client for the API Transfer backend.
// In dev, Vite proxies these paths to Django; in production Django serves both
// the SPA and the API from the same origin.

const MIGRATIONS_BASE = "/api/migrations";
const BILLING_BASE = "/api/billing";

let apiKey = "";
let accountEmail = "";

export function setApiKey(key: string): void {
  apiKey = key.trim();
}

export function getApiKey(): string {
  return apiKey;
}

export function setAccountEmail(email: string): void {
  accountEmail = email.trim();
}

export function getAccountEmail(): string {
  return accountEmail;
}

function headers(json = true): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  if (apiKey) h["x-api-key"] = apiKey;
  if (accountEmail) h["x-account-email"] = accountEmail;
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

export interface TransferStartRequest {
  mode: "queue" | "demand";
  only?: string[];
  limit?: number;
  redeployExisting?: boolean;
  verify?: boolean;
  verifyTimeout?: number;
  verifyInterval?: number;
  serviceTimeout?: number;
  allowOverlap?: boolean;
  dryRun?: boolean;
  queueOnly?: boolean;
  queuePriority?: number;
  maxRetries?: number;
  replayFromCheckpoint?: boolean;
  workspaceConcurrencyCap?: number;
}

export interface TransferRunStatus {
  id: string;
  status?: string;
  step?: string;
  stepState?: Record<string, unknown>;
  running: boolean;
  exitCode: number | null;
  startedAt: string;
  finishedAt?: string | null;
  createdAt?: string;
  updatedAt?: string;
  mode?: string;
  requestedBy?: string;
  options?: Record<string, unknown>;
  queuePriority?: number;
  queueAgeSeconds?: number;
  queueAgeBoost?: number;
  queueEffectivePriority?: number;
  agingWindowSeconds?: number;
  maxAgingBoost?: number;
  retryCount?: number;
  maxRetries?: number;
  nextRetryAt?: string | null;
  lastError?: string;
  attemptStartedAt?: string | null;
  leaseOwner?: string;
  leaseExpiresAt?: string | null;
  heartbeatAt?: string | null;
  logPath?: string;
  command: string[];
  logTail: string;
}

export interface TransferHistoryResponse {
  runs: TransferRunStatus[];
  nextCursor: string | null;
}

export interface TransferWorkspaceMetricRow {
  workspaceId: number;
  workspaceName: string;
  count: number;
}

export interface TransferMetricsResponse {
  summary: {
    running: number;
    queued: number;
    retryable: number;
    deadLetter: number;
    total: number;
  };
  schedulingPolicy: {
    workerBatchLimit: number;
    pollIntervalSeconds: number;
    leaseTtlSeconds: number;
    heartbeatIntervalSeconds: number;
    workspaceConcurrencyCap: number;
    agingWindowSeconds: number;
    maxAgingBoost: number;
  };
  alerts: {
    deadLetter: { active: boolean; count: number; threshold: number };
    retryableBacklog: { active: boolean; count: number; threshold: number };
    staleLeases: { active: boolean; count: number; threshold: number };
  };
  workspace: {
    id: number;
    name: string;
    running: number;
    queued: number;
    retryable: number;
    deadLetter: number;
    total: number;
  };
  runningByWorkspace: TransferWorkspaceMetricRow[];
  queuedByWorkspace: TransferWorkspaceMetricRow[];
  deadLetterByWorkspace: TransferWorkspaceMetricRow[];
  generatedAt: string;
}

export async function startTransfer(body: TransferStartRequest): Promise<{ run: TransferRunStatus }> {
  return postMigrations("/transfer/start", body);
}

export async function stopTransfer(): Promise<{ stopped: boolean; message?: string; run?: TransferRunStatus }> {
  return postMigrations("/transfer/stop", {});
}

export async function getTransferStatus(): Promise<{ run: TransferRunStatus }> {
  return getMigrations("/transfer/status");
}

export async function getTransferHistory(limit = 10, cursor = ""): Promise<TransferHistoryResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  return getMigrations(`/transfer/history?${params.toString()}`);
}

export async function getTransferMetrics(): Promise<TransferMetricsResponse> {
  return getMigrations("/transfer/metrics");
}

export async function replayTransfer(runId: string): Promise<{ run: TransferRunStatus }> {
  return postMigrations(`/transfer/replay/${encodeURIComponent(runId)}`, {});
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

export async function getAccount(): Promise<any> {
  const res = await fetch(`${BILLING_BASE}/account`, { headers: headers(false) });
  return parse(res);
}

export async function startCheckout(
  email: string,
  planSlug: string,
  registeredDomain: string,
  maxInstances = 1,
): Promise<{ url: string; sessionId: string }> {
  const res = await fetch(`${BILLING_BASE}/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, planSlug, registeredDomain, maxInstances }),
  });
  return parse(res);
}

export async function getSubscription(email: string): Promise<any> {
  const res = await fetch(`${BILLING_BASE}/subscription?email=${encodeURIComponent(email)}`);
  return parse(res);
}
