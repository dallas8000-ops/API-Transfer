import { DetectedFramework } from "./deployment";
import { ProviderType } from "./types";

export type DiagnosticSeverity = "critical" | "high" | "medium" | "low" | "info";

export type DiagnosticCategory =
  | "configuration"
  | "security"
  | "dependency"
  | "runtime"
  | "networking"
  | "observability";

/**
 * Describes a concrete, machine-applicable change that resolves an issue.
 * The engine never mutates external systems; it produces a corrected
 * configuration the operator can review and re-deploy.
 */
export interface DiagnosticFix {
  /** Human-readable summary of what the fix does. */
  summary: string;
  /** Where the change applies. */
  target: "environment" | "secrets" | "packageJson" | "files" | "request";
  /** Field/key the change touches (e.g. env var name or package.json path). */
  field?: string;
  /** Suggested value (secret values are masked, never echoed in plaintext). */
  suggestedValue?: string;
}

export interface DiagnosticIssue {
  id: string;
  category: DiagnosticCategory;
  severity: DiagnosticSeverity;
  title: string;
  detail: string;
  /** What part of the project the issue affects. */
  affects: string;
  recommendation: string;
  /** True when the engine can resolve this automatically and safely. */
  autoFixable: boolean;
  fix?: DiagnosticFix;
}

/** A project/application to analyze. Mirrors the deployment request shape. */
export interface DiagnosisRequest {
  appName: string;
  targetProvider: ProviderType;
  files: string[];
  packageJson?: Record<string, unknown>;
  environment: Record<string, string>;
  secrets: { key: string; value: string }[];
  domain?: string;
  enableStripe: boolean;
  enableMonitoring: boolean;
  enableBackups: boolean;
  targetEnvironment: "dev" | "stage" | "prod";
  requestedBy: string;
}

export interface DiagnosisReport {
  diagnosisId: string;
  appName: string;
  framework: DetectedFramework;
  issues: DiagnosticIssue[];
  summary: {
    total: number;
    bySeverity: Record<DiagnosticSeverity, number>;
    autoFixable: number;
    healthScore: number;
  };
  analyzedAt: string;
  integrityHash: string;
}

export interface AppliedFix {
  issueId: string;
  summary: string;
  target: DiagnosticFix["target"];
  field?: string;
}

export interface FixResult {
  diagnosisId: string;
  appName: string;
  applied: AppliedFix[];
  skipped: { issueId: string; reason: string }[];
  /** Corrected, redacted project configuration ready for re-deployment. */
  correctedConfig: {
    environment: Record<string, string>;
    secretKeys: string[];
    packageJsonScripts?: Record<string, string>;
    addedFiles: string[];
  };
  /** Diagnostics re-run after applying fixes. */
  residualReport: DiagnosisReport;
  integrityHash: string;
}
