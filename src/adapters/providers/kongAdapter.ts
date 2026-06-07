import { CanonicalMigrationSpec } from "../../domain/types";
import { ProviderAdapter, ProviderSnapshot } from "../base";

export class KongAdapter implements ProviderAdapter {
  readonly provider = "kong" as const;

  async discover(appIdentifier: string): Promise<ProviderSnapshot> {
    return { provider: this.provider, raw: { workspace: appIdentifier, source: "kong-admin-api" } };
  }

  async toCanonical(snapshot: ProviderSnapshot): Promise<CanonicalMigrationSpec> {
    return {
      appName: String(snapshot.raw.workspace ?? "unknown-kong-workspace"),
      sourceProvider: "kong",
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
      declarativeConfig: {
        _format_version: "3.0",
        services: spec.services.map((service) => ({
          name: service.name,
          host: `${service.name}.internal`,
          protocol: "https"
        }))
      }
    };
  }

  async validate(spec: CanonicalMigrationSpec): Promise<string[]> {
    const warnings: string[] = [];
    if (spec.domains.some((d) => !d.tlsRequired)) {
      warnings.push("Kong recommends TLS-enabled domains for managed routes.");
    }
    return warnings;
  }
}
