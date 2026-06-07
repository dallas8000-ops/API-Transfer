import { CanonicalMigrationSpec, MigrationPlan, ProviderType } from "../domain/types";
import { getAdapter } from "../adapters/registry";
import { decryptSecret, encryptSecret } from "../security/cryptoVault";
import { evaluatePolicies } from "./policyEngine";
import { createPlan } from "./planner";
import { integrityHash } from "../security/integrity";
import { auditLog } from "./auditLog";
import { snapshotStore } from "./snapshotStore";
import { verifyMigration, VerificationReport } from "./verification";

export interface PlanResult {
  plan: MigrationPlan;
  encryptedSecrets: Record<string, { iv: string; authTag: string; ciphertext: string }>;
}

export interface ApplyResult {
  deploymentPayload: Record<string, unknown>;
  executedAt: string;
  integrityHash: string;
  verification: VerificationReport;
  snapshotId: string;
}

export interface RollbackResult {
  planId: string;
  rolledBackTo: string;
  executedAt: string;
}

function encryptSpecSecrets(spec: CanonicalMigrationSpec) {
  const encrypted: Record<string, { iv: string; authTag: string; ciphertext: string }> = {};

  for (const service of spec.services) {
    for (const secret of service.secrets) {
      encrypted[`${service.name}.${secret.key}`] = encryptSecret(secret.value);
    }
  }

  return encrypted;
}

function hydrateSecrets(spec: CanonicalMigrationSpec, encryptedSecrets: Record<string, { iv: string; authTag: string; ciphertext: string }>) {
  const clone = structuredClone(spec);

  for (const service of clone.services) {
    for (const secret of service.secrets) {
      const secretPath = `${service.name}.${secret.key}`;
      const encrypted = encryptedSecrets[secretPath];
      if (encrypted) {
        secret.value = decryptSecret(encrypted);
      }
    }
  }

  return clone;
}

export async function generatePlan(spec: CanonicalMigrationSpec): Promise<PlanResult> {
  const sourceAdapter = getAdapter(spec.sourceProvider);
  const targetAdapter = getAdapter(spec.targetProvider);

  const providerWarnings = [
    ...(await sourceAdapter.validate(spec)),
    ...(await targetAdapter.validate(spec))
  ];

  const policy = evaluatePolicies(spec);
  const allWarnings = [...providerWarnings, ...policy.violations];

  const plan = createPlan(spec, allWarnings);
  const encryptedSecrets = encryptSpecSecrets(spec);

  auditLog.record("plan", spec.metadata.requestedBy, { appName: spec.appName, warnings: allWarnings }, plan.planId);

  return { plan, encryptedSecrets };
}

export async function applyPlan(args: {
  spec: CanonicalMigrationSpec;
  plan: MigrationPlan;
  encryptedSecrets: Record<string, { iv: string; authTag: string; ciphertext: string }>;
  approvedBy: string;
}): Promise<ApplyResult> {
  const { spec, plan, encryptedSecrets, approvedBy } = args;
  if (!approvedBy || approvedBy.trim().length < 3) {
    throw new Error("approvedBy is required for apply");
  }

  const expectedHash = integrityHash({
    spec,
    planDraft: {
      summary: plan.summary,
      riskScore: plan.riskScore,
      confidence: plan.confidence,
      steps: plan.steps,
      warnings: plan.warnings,
      createdAt: plan.createdAt
    }
  });

  if (expectedHash !== plan.integrityHash) {
    throw new Error("Plan integrity check failed");
  }

  const snapshot = snapshotStore.capture(plan.planId, spec);

  const hydratedSpec = hydrateSecrets(spec, encryptedSecrets);
  const targetAdapter = getAdapter(hydratedSpec.targetProvider as ProviderType);
  const deploymentPayload = await targetAdapter.fromCanonical(hydratedSpec);

  const verification = verifyMigration(hydratedSpec);
  const executedAt = new Date().toISOString();

  auditLog.record("apply", approvedBy, { appName: spec.appName, verificationPassed: verification.passed }, plan.planId);
  auditLog.record("verify", approvedBy, { checks: verification.checks }, plan.planId);

  return {
    deploymentPayload,
    executedAt,
    integrityHash: integrityHash({ deploymentPayload, approvedBy }),
    verification,
    snapshotId: snapshot.planId
  };
}

export async function rollbackPlan(planId: string, actor: string): Promise<RollbackResult> {
  if (!actor || actor.trim().length < 3) {
    throw new Error("actor is required for rollback");
  }

  const snapshot = snapshotStore.get(planId);
  if (!snapshot) {
    throw new Error("No rollback snapshot found for this plan ID");
  }

  const expected = integrityHash({
    planId: snapshot.planId,
    redactedSpec: snapshot.redactedSpec,
    capturedAt: snapshot.capturedAt
  });

  if (expected !== snapshot.integrityHash) {
    throw new Error("Rollback snapshot integrity check failed");
  }

  const executedAt = new Date().toISOString();
  auditLog.record("rollback", actor, { appName: snapshot.appName, targetProvider: snapshot.targetProvider }, planId);
  snapshotStore.remove(planId);

  return {
    planId,
    rolledBackTo: snapshot.capturedAt,
    executedAt
  };
}
