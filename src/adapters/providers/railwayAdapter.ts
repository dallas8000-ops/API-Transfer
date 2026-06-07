import { CanonicalMigrationSpec } from "../../domain/types";
import { ProviderAdapter, ProviderSnapshot } from "../base";

export class RailwayAdapter implements ProviderAdapter {
  readonly provider = "railway" as const;

  async discover(appIdentifier: string): Promise<ProviderSnapshot> {
    return { provider: this.provider, raw: { projectId: appIdentifier, source: "railway-api" } };
  }

  async toCanonical(snapshot: ProviderSnapshot): Promise<CanonicalMigrationSpec> {
    return {
      appName: String(snapshot.raw.projectId ?? "unknown-railway-project"),
      sourceProvider: "railway",
      targetProvider: "render",
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
      railway: {
        services: spec.services.map((service) => ({
          name: service.name,
          startCommand: service.startCommand
        }))
      }
    };
  }

  async validate(_spec: CanonicalMigrationSpec): Promise<string[]> {
    return [];
  }
}
