import { CanonicalMigrationSpec } from "../../domain/types";
import { ProviderAdapter, ProviderSnapshot } from "../base";

export class TerraformAdapter implements ProviderAdapter {
  readonly provider = "terraform" as const;

  async discover(appIdentifier: string): Promise<ProviderSnapshot> {
    return { provider: this.provider, raw: { workspace: appIdentifier, source: "terraform-state" } };
  }

  async toCanonical(snapshot: ProviderSnapshot): Promise<CanonicalMigrationSpec> {
    return {
      appName: String(snapshot.raw.workspace ?? "unknown-terraform-workspace"),
      sourceProvider: "terraform",
      targetProvider: "railway",
      services: [],
      domains: [],
      databases: [],
      metadata: {
        requestedBy: "system",
        requestedAt: new Date().toISOString(),
        environment: "stage"
      }
    };
  }

  async fromCanonical(spec: CanonicalMigrationSpec): Promise<Record<string, unknown>> {
    return {
      terraform: {
        required_version: ">= 1.6.0",
        resources: spec.services.map((s) => ({ type: "service", name: s.name }))
      }
    };
  }

  async validate(spec: CanonicalMigrationSpec): Promise<string[]> {
    const warnings: string[] = [];
    if (spec.services.length === 0) {
      warnings.push("Terraform generation is more accurate when at least one service is defined.");
    }
    return warnings;
  }
}
