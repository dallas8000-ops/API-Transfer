import { randomUUID } from "crypto";
import { CanonicalMigrationSpec, MigrationPlan } from "../domain/types";
import { integrityHash } from "../security/integrity";
import { buildDiff } from "./diff";

export function createPlan(spec: CanonicalMigrationSpec, warnings: string[]): MigrationPlan {
  const diff = buildDiff(spec);
  const riskScore = Math.min(100, warnings.length * 15 + diff.missingServices.length * 20 + diff.missingDomains.length * 20);
  const confidence = Math.max(10, 95 - warnings.length * 8 - diff.missingServices.length * 10);

  const steps = [
    `Discover resources from ${spec.sourceProvider}`,
    `Normalize source into canonical migration spec`,
    `Validate policy and provider constraints`,
    `Generate target artifacts for ${spec.targetProvider}`,
    "Run pre-deploy checks and dry-run",
    "Apply migration and run post-transfer health checks"
  ];

  const planDraft = {
    summary: `Migration for '${spec.appName}' from ${spec.sourceProvider} to ${spec.targetProvider}`,
    riskScore,
    confidence,
    steps,
    warnings,
    createdAt: new Date().toISOString()
  };

  return {
    planId: randomUUID(),
    ...planDraft,
    integrityHash: integrityHash({ spec, planDraft })
  };
}
