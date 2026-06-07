import { CanonicalMigrationSpec } from "../domain/types";

export interface MigrationDiff {
  missingServices: string[];
  missingDomains: string[];
  providerTransition: string;
}

export function buildDiff(spec: CanonicalMigrationSpec): MigrationDiff {
  return {
    missingServices: spec.services.filter((s) => !s.startCommand).map((s) => s.name),
    missingDomains: spec.domains.filter((d) => !d.tlsRequired).map((d) => d.host),
    providerTransition: `${spec.sourceProvider} -> ${spec.targetProvider}`
  };
}
