import { env } from "../config/env";
import { httpJson } from "./httpClient";
import { resolveProviderToken, getIntegrationToken } from "./credentials";

export interface SupabaseProject {
  id: string;
  name: string;
  region: string;
  organization_id?: string;
  database?: {
    host?: string;
    version?: string;
  };
}

/**
 * Live Supabase discovery via the Management API. Retrieves project metadata
 * used to build the canonical migration spec (region, database version).
 */
export async function discoverSupabaseProject(projectRef: string): Promise<SupabaseProject> {
  const token = resolveProviderToken("supabase");

  const project = await httpJson<SupabaseProject>("supabase", env.SUPABASE_API_BASE_URL, {
    method: "GET",
    path: `/v1/projects/${encodeURIComponent(projectRef)}`,
    token
  });

  return project;
}

export interface ProvisionDbInput {
  appName: string;
  /** Strong database password; treated as a secret and never logged. */
  dbPassword: string;
  region?: string;
}

export interface ProvisionDbResult {
  projectRef: string;
  region: string;
  host: string;
}

interface CreatedProject {
  id: string;
  ref?: string;
  region: string;
  database?: { host?: string };
}

/**
 * Live Supabase Postgres provisioning via the Management API. Creates a new
 * project (which includes a managed Postgres database). The db password is a
 * secret supplied by the caller and is never logged here.
 */
export async function provisionSupabaseDatabase(input: ProvisionDbInput): Promise<ProvisionDbResult> {
  const token = getIntegrationToken("supabase");
  if (!token) {
    throw new Error("SUPABASE_ACCESS_TOKEN is not configured");
  }
  if (!env.SUPABASE_ORG_ID) {
    throw new Error("SUPABASE_ORG_ID is not configured");
  }

  const region = input.region ?? env.SUPABASE_DEFAULT_REGION;

  const project = await httpJson<CreatedProject>("supabase", env.SUPABASE_API_BASE_URL, {
    method: "POST",
    path: "/v1/projects",
    token,
    body: {
      name: input.appName,
      organization_id: env.SUPABASE_ORG_ID,
      region,
      db_pass: input.dbPassword,
      plan: "free"
    }
  });

  const projectRef = project.ref ?? project.id;
  return {
    projectRef,
    region: project.region ?? region,
    host: project.database?.host ?? `db.${projectRef}.supabase.co`
  };
}
