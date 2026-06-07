import { CanonicalMigrationSpec } from "../../domain/types";
import { hasProviderToken } from "../../providers/credentials";
import { discoverFlyApp } from "../../providers/flyClient";
import { ProviderAdapter, ProviderSnapshot } from "../base";

export class FlyAdapter implements ProviderAdapter {
  readonly provider = "fly" as const;

  async discover(appIdentifier: string): Promise<ProviderSnapshot> {
    if (!hasProviderToken("fly")) {
      return { provider: this.provider, raw: { appIdentifier, source: "fly-stub", live: false } };
    }

    const details = await discoverFlyApp(appIdentifier);
    return {
      provider: this.provider,
      raw: {
        appIdentifier,
        source: "fly-api",
        live: true,
        regions: details.machines.map((m) => m.region),
        machineCount: details.machines.length
      }
    };
  }

  async toCanonical(snapshot: ProviderSnapshot): Promise<CanonicalMigrationSpec> {
    const regions = Array.isArray(snapshot.raw.regions) ? (snapshot.raw.regions as string[]) : [];
    const primaryRegion = regions[0];
    return {
      appName: String(snapshot.raw.appIdentifier ?? "unknown-fly-app"),
      sourceProvider: "fly",
      targetProvider: "railway",
      services: primaryRegion
        ? [
            {
              name: String(snapshot.raw.appIdentifier ?? "fly-service"),
              runtime: "docker",
              region: primaryRegion,
              environment: {},
              secrets: []
            }
          ]
        : [],
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
      flyToml: {
        app: spec.appName,
        primary_region: spec.services[0]?.region ?? "iad"
      }
    };
  }

  async validate(spec: CanonicalMigrationSpec): Promise<string[]> {
    const warnings: string[] = [];
    if (spec.services.some((s) => !s.region)) {
      warnings.push("Fly deployment should define explicit regions for global control.");
    }
    return warnings;
  }
}
