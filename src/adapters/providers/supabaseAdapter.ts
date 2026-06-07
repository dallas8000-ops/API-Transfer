import { CanonicalMigrationSpec } from "../../domain/types";
import { hasProviderToken } from "../../providers/credentials";
import { discoverSupabaseProject } from "../../providers/supabaseClient";
import { ProviderAdapter, ProviderSnapshot } from "../base";

export class SupabaseAdapter implements ProviderAdapter {
  readonly provider = "supabase" as const;

  async discover(appIdentifier: string): Promise<ProviderSnapshot> {
    if (!hasProviderToken("supabase")) {
      return { provider: this.provider, raw: { projectRef: appIdentifier, source: "supabase-stub", live: false } };
    }

    const project = await discoverSupabaseProject(appIdentifier);
    return {
      provider: this.provider,
      raw: {
        projectRef: appIdentifier,
        source: "supabase-api",
        live: true,
        region: project.region,
        databaseVersion: project.database?.version
      }
    };
  }

  async toCanonical(snapshot: ProviderSnapshot): Promise<CanonicalMigrationSpec> {
    const databaseVersion = typeof snapshot.raw.databaseVersion === "string" ? snapshot.raw.databaseVersion : undefined;
    return {
      appName: String(snapshot.raw.projectRef ?? "unknown-supabase-project"),
      sourceProvider: "supabase",
      targetProvider: "railway",
      services: [],
      domains: [],
      databases: [
        {
          name: "primary",
          engine: "postgres",
          version: databaseVersion
        }
      ],
      metadata: {
        requestedBy: "system",
        requestedAt: new Date().toISOString(),
        environment: "stage"
      }
    };
  }

  async fromCanonical(spec: CanonicalMigrationSpec): Promise<Record<string, unknown>> {
    return {
      sqlMigrations: spec.databases.map((db) => ({ name: db.name, engine: db.engine })),
      rlsPolicies: []
    };
  }

  async validate(spec: CanonicalMigrationSpec): Promise<string[]> {
    const warnings: string[] = [];
    if (!spec.databases.some((d) => d.engine === "postgres")) {
      warnings.push("Supabase targets should include a Postgres database.");
    }
    return warnings;
  }
}
