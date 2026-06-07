import { env } from "../config/env";
import { httpJson } from "./httpClient";
import { resolveProviderToken } from "./credentials";

export interface FlyMachine {
  id: string;
  name: string;
  region: string;
  state: string;
  config?: {
    image?: string;
    env?: Record<string, string>;
  };
}

export interface FlyAppDetails {
  appName: string;
  organization?: string;
  machines: FlyMachine[];
}

/**
 * Live Fly.io discovery via the Machines API. Returns app machines and their
 * regions/config so the canonical mapper can build a migration spec.
 */
export async function discoverFlyApp(appName: string): Promise<FlyAppDetails> {
  const token = resolveProviderToken("fly");

  const machines = await httpJson<FlyMachine[]>("fly", env.FLY_API_BASE_URL, {
    method: "GET",
    path: `/v1/apps/${encodeURIComponent(appName)}/machines`,
    token
  });

  return {
    appName,
    machines: Array.isArray(machines) ? machines : []
  };
}

export interface FlyDeployInput {
  appName: string;
  image: string;
  region: string;
  port: number;
  env: Record<string, string>;
}

export interface FlyDeployResult {
  appName: string;
  machineId: string;
  region: string;
  hostname: string;
}

/**
 * Live Fly.io deploy: ensures the app exists, then creates a machine running
 * the given image. Secrets must be set separately via the secrets API and are
 * never embedded here in plaintext beyond the caller-provided env map.
 */
export async function deployFlyApp(input: FlyDeployInput): Promise<FlyDeployResult> {
  const token = resolveProviderToken("fly");

  // Ensure the app exists (ignore 409/422 if it already does).
  try {
    await httpJson("fly", env.FLY_API_BASE_URL, {
      method: "POST",
      path: "/v1/apps",
      token,
      body: { app_name: input.appName, org_slug: env.FLY_ORG_SLUG }
    });
  } catch (error) {
    // App may already exist; continue to machine creation.
    if (!(error instanceof Error) || !/409|422|already/i.test(error.message)) {
      throw error;
    }
  }

  const machine = await httpJson<FlyMachine>("fly", env.FLY_API_BASE_URL, {
    method: "POST",
    path: `/v1/apps/${encodeURIComponent(input.appName)}/machines`,
    token,
    body: {
      region: input.region,
      config: {
        image: input.image,
        env: input.env,
        services: [
          {
            ports: [
              { port: 443, handlers: ["tls", "http"] },
              { port: 80, handlers: ["http"] }
            ],
            protocol: "tcp",
            internal_port: input.port
          }
        ]
      }
    }
  });

  return {
    appName: input.appName,
    machineId: machine.id,
    region: machine.region ?? input.region,
    hostname: `${input.appName}.fly.dev`
  };
}
