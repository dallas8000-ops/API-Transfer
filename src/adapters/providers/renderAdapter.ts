import { CanonicalMigrationSpec } from "../../domain/types";
import { ProviderAdapter, ProviderSnapshot } from "../base";

export class RenderAdapter implements ProviderAdapter {
  readonly provider = "render" as const;

  async discover(appIdentifier: string): Promise<ProviderSnapshot> {
    return { provider: this.provider, raw: { serviceId: appIdentifier, source: "render-api" } };
  }

  async toCanonical(snapshot: ProviderSnapshot): Promise<CanonicalMigrationSpec> {
    return {
      appName: String(snapshot.raw.serviceId ?? "unknown-render-service"),
      sourceProvider: "render",
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
      blueprint: {
        services: spec.services.map((service) => ({
          name: service.name,
          env: service.runtime,
          region: service.region ?? "oregon"
        }))
      }
    };
  }

  async validate(_spec: CanonicalMigrationSpec): Promise<string[]> {
    return [];
  }
}
