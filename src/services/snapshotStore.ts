import { CanonicalMigrationSpec } from "../domain/types";
import { integrityHash } from "../security/integrity";
import { redactSensitiveValues } from "../security/redaction";

export interface RollbackSnapshot {
  planId: string;
  appName: string;
  targetProvider: string;
  capturedAt: string;
  redactedSpec: unknown;
  integrityHash: string;
}

class SnapshotStore {
  private snapshots = new Map<string, RollbackSnapshot>();

  capture(planId: string, spec: CanonicalMigrationSpec): RollbackSnapshot {
    const redactedSpec = redactSensitiveValues(spec);
    const capturedAt = new Date().toISOString();

    const snapshot: RollbackSnapshot = {
      planId,
      appName: spec.appName,
      targetProvider: spec.targetProvider,
      capturedAt,
      redactedSpec,
      integrityHash: integrityHash({ planId, redactedSpec, capturedAt })
    };

    this.snapshots.set(planId, snapshot);
    return snapshot;
  }

  get(planId: string): RollbackSnapshot | undefined {
    return this.snapshots.get(planId);
  }

  remove(planId: string): void {
    this.snapshots.delete(planId);
  }
}

export const snapshotStore = new SnapshotStore();
