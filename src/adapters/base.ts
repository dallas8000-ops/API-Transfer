import { CanonicalMigrationSpec, ProviderType } from "../domain/types";

export interface ProviderSnapshot {
  provider: ProviderType;
  raw: Record<string, unknown>;
}

export interface ProviderAdapter {
  readonly provider: ProviderType;
  discover(appIdentifier: string): Promise<ProviderSnapshot>;
  toCanonical(snapshot: ProviderSnapshot): Promise<CanonicalMigrationSpec>;
  fromCanonical(spec: CanonicalMigrationSpec): Promise<Record<string, unknown>>;
  validate(spec: CanonicalMigrationSpec): Promise<string[]>;
}
