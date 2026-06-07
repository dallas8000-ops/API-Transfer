export type ProviderType = "render" | "railway" | "fly" | "kong" | "terraform" | "supabase";

export interface SecretRef {
  key: string;
  value: string;
}

export interface ServiceSpec {
  name: string;
  runtime: "node" | "python" | "go" | "docker" | "static";
  buildCommand?: string;
  startCommand?: string;
  region?: string;
  replicas?: number;
  environment: Record<string, string>;
  secrets: SecretRef[];
}

export interface DomainSpec {
  host: string;
  path?: string;
  tlsRequired: boolean;
}

export interface DatabaseSpec {
  name: string;
  engine: "postgres" | "mysql" | "redis";
  version?: string;
}

export interface CanonicalMigrationSpec {
  appName: string;
  sourceProvider: ProviderType;
  targetProvider: ProviderType;
  services: ServiceSpec[];
  domains: DomainSpec[];
  databases: DatabaseSpec[];
  metadata: {
    requestedBy: string;
    requestedAt: string;
    environment: "dev" | "stage" | "prod";
  };
}

export interface MigrationPlan {
  planId: string;
  summary: string;
  riskScore: number;
  confidence: number;
  steps: string[];
  warnings: string[];
  createdAt: string;
  integrityHash: string;
}
