import { ProviderType } from "./types";

export type FrameworkId =
  | "nextjs"
  | "react"
  | "vue"
  | "express"
  | "nestjs"
  | "django"
  | "flask"
  | "fastapi"
  | "go"
  | "static"
  | "unknown";

export interface DetectedFramework {
  framework: FrameworkId;
  runtime: "node" | "python" | "go" | "docker" | "static";
  buildCommand?: string;
  startCommand?: string;
  defaultPort: number;
  confidence: number;
}

export interface DeploymentRequest {
  appName: string;
  targetProvider: ProviderType;
  region?: string;
  /** File paths present in the uploaded project, used for framework detection. */
  files: string[];
  /** Optional raw package.json contents to refine Node framework detection. */
  packageJson?: Record<string, unknown>;
  environment: Record<string, string>;
  secrets: { key: string; value: string }[];
  domain?: string;
  enableStripe: boolean;
  enableMonitoring: boolean;
  enableBackups: boolean;
  requestedBy: string;
  targetEnvironment: "dev" | "stage" | "prod";
}

export type StageStatus = "succeeded" | "skipped" | "failed";

export interface StageResult {
  stage: string;
  status: StageStatus;
  detail: string;
  data?: Record<string, unknown>;
}

export interface ReadinessCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface DeploymentResult {
  deploymentId: string;
  appName: string;
  framework: DetectedFramework;
  stages: StageResult[];
  readiness: ReadinessCheck[];
  liveUrl: string;
  succeeded: boolean;
  startedAt: string;
  finishedAt: string;
  integrityHash: string;
}
