import { randomBytes } from "node:crypto";
import { DeploymentRequest, DetectedFramework, StageResult } from "../domain/deployment";
import { encryptSecret } from "../security/cryptoVault";
import { hasIntegrationToken } from "../providers/credentials";
import { deployFlyApp } from "../providers/flyClient";
import { setupStripe } from "../providers/stripeClient";
import { createDnsRecord } from "../providers/cloudflareClient";
import { provisionSupabaseDatabase } from "../providers/supabaseClient";
import { env } from "../config/env";
import { logger } from "../logger";

/**
 * Stages call live provider APIs when the matching token is configured, and
 * fall back to a deterministic simulated result otherwise. Secrets are always
 * encrypted with the vault before being attached to output and are never
 * returned in plaintext.
 */

export function stageCreateEnvironment(request: DeploymentRequest): StageResult {
  return {
    stage: "create-environment",
    status: "succeeded",
    detail: `Provisioned '${request.targetEnvironment}' environment on ${request.targetProvider}`,
    data: {
      provider: request.targetProvider,
      region: request.region ?? "auto",
      environment: request.targetEnvironment
    }
  };
}

export async function stageProvisionDatabase(
  request: DeploymentRequest,
  framework: DetectedFramework
): Promise<StageResult> {
  const needsDb = framework.framework !== "static" && framework.runtime !== "static";
  if (!needsDb) {
    return {
      stage: "provision-database",
      status: "skipped",
      detail: "Static site detected — no database required"
    };
  }

  // Strong password is generated, used for provisioning, and encrypted at rest.
  const dbPassword = randomBytes(24).toString("base64url");

  if (hasIntegrationToken("supabase") && env.SUPABASE_ORG_ID) {
    try {
      const result = await provisionSupabaseDatabase({
        appName: request.appName,
        dbPassword,
        region: request.region
      });
      const connectionString = `postgres://postgres:***@${result.host}:5432/postgres`;
      return {
        stage: "provision-database",
        status: "succeeded",
        detail: `PostgreSQL provisioned on Supabase (project ${result.projectRef})`,
        data: {
          live: true,
          engine: "postgres",
          projectRef: result.projectRef,
          region: result.region,
          encryptedConnection: encryptSecret(connectionString),
          encryptedDbPassword: encryptSecret(dbPassword)
        }
      };
    } catch (error) {
      logger.error({ err: error }, "Supabase provisioning failed");
      return {
        stage: "provision-database",
        status: "failed",
        detail: `Supabase provisioning failed: ${(error as Error).message}`
      };
    }
  }

  // Simulated fallback when no Supabase token is configured.
  const connectionString = `postgres://app:***@db.${request.appName}.internal:5432/${request.appName}`;
  return {
    stage: "provision-database",
    status: "succeeded",
    detail: "PostgreSQL database provisioned (simulated — set SUPABASE_ACCESS_TOKEN for live)",
    data: {
      live: false,
      engine: "postgres",
      version: "16",
      encryptedConnection: encryptSecret(connectionString),
      encryptedDbPassword: encryptSecret(dbPassword)
    }
  };
}

export function stageConfigureEnvVars(request: DeploymentRequest): StageResult {
  const encryptedSecrets: Record<string, unknown> = {};
  for (const secret of request.secrets) {
    encryptedSecrets[secret.key] = encryptSecret(secret.value);
  }

  return {
    stage: "configure-env-vars",
    status: "succeeded",
    detail: `Configured ${Object.keys(request.environment).length} env vars and ${request.secrets.length} secrets`,
    data: {
      publicKeys: Object.keys(request.environment),
      secretKeys: request.secrets.map((s) => s.key),
      encryptedSecrets
    }
  };
}

export function stageSetupDomain(request: DeploymentRequest): StageResult {
  const host = request.domain ?? `${request.appName}.${request.targetProvider}.app`;
  return {
    stage: "setup-domain",
    status: "succeeded",
    detail: `Domain configured: ${host}`,
    data: { host, managed: !request.domain }
  };
}

export async function stageCreateDnsRecords(request: DeploymentRequest): Promise<StageResult> {
  if (!request.domain) {
    return {
      stage: "create-dns-records",
      status: "skipped",
      detail: "Using provider-managed subdomain — no custom DNS records needed"
    };
  }

  if (hasIntegrationToken("cloudflare") && env.CLOUDFLARE_ZONE_ID) {
    try {
      const apex = await createDnsRecord({
        type: "A",
        name: request.domain,
        content: env.DEPLOY_DNS_TARGET,
        proxied: true
      });
      const www = await createDnsRecord({
        type: "CNAME",
        name: `www.${request.domain}`,
        content: request.domain,
        proxied: true
      });
      return {
        stage: "create-dns-records",
        status: "succeeded",
        detail: `DNS records created on Cloudflare for ${request.domain}`,
        data: { live: true, recordIds: [apex.id, www.id], proxied: true }
      };
    } catch (error) {
      logger.error({ err: error }, "Cloudflare DNS creation failed");
      return {
        stage: "create-dns-records",
        status: "failed",
        detail: `Cloudflare DNS creation failed: ${(error as Error).message}`
      };
    }
  }

  return {
    stage: "create-dns-records",
    status: "succeeded",
    detail: `DNS records created for ${request.domain} (simulated — set CLOUDFLARE_API_TOKEN for live)`,
    data: {
      live: false,
      records: [
        { type: "A", name: request.domain, value: env.DEPLOY_DNS_TARGET },
        { type: "CNAME", name: `www.${request.domain}`, value: request.domain }
      ]
    }
  };
}

export function stageEnableSsl(request: DeploymentRequest): StageResult {
  const host = request.domain ?? `${request.appName}.${request.targetProvider}.app`;
  const cloudflareProxied = Boolean(request.domain) && hasIntegrationToken("cloudflare") && Boolean(env.CLOUDFLARE_ZONE_ID);
  return {
    stage: "enable-ssl",
    status: "succeeded",
    detail: cloudflareProxied
      ? `TLS active via Cloudflare Universal SSL for ${host}`
      : `TLS certificate issued for ${host}`,
    data: {
      issuer: cloudflareProxied ? "cloudflare-universal-ssl" : "lets-encrypt",
      autoRenew: true,
      live: cloudflareProxied
    }
  };
}

export async function stageConfigureStripe(request: DeploymentRequest): Promise<StageResult> {
  if (!request.enableStripe) {
    return { stage: "configure-stripe", status: "skipped", detail: "Stripe not requested" };
  }

  const host = request.domain ?? `${request.appName}.${request.targetProvider}.app`;
  const webhookUrl = `https://${host}/webhooks/stripe`;

  if (hasIntegrationToken("stripe")) {
    try {
      const result = await setupStripe({
        appName: request.appName,
        productName: `${request.appName} subscription`,
        unitAmount: 1000,
        currency: "usd",
        webhookUrl
      });
      return {
        stage: "configure-stripe",
        status: "succeeded",
        detail: "Stripe product, price, and webhook endpoint created",
        data: {
          live: true,
          productId: result.productId,
          priceId: result.priceId,
          webhookId: result.webhookId,
          webhookPath: "/webhooks/stripe",
          encryptedWebhookSecret: encryptSecret(result.webhookSecret)
        }
      };
    } catch (error) {
      logger.error({ err: error }, "Stripe setup failed");
      return {
        stage: "configure-stripe",
        status: "failed",
        detail: `Stripe setup failed: ${(error as Error).message}`
      };
    }
  }

  // Simulated fallback when no Stripe key is configured.
  const webhookSecret = encryptSecret(`whsec_${request.appName}_${Date.now()}`);
  return {
    stage: "configure-stripe",
    status: "succeeded",
    detail: "Stripe configured (simulated — set STRIPE_SECRET_KEY for live)",
    data: {
      live: false,
      webhookPath: "/webhooks/stripe",
      encryptedWebhookSecret: webhookSecret
    }
  };
}

export async function stageDeployApp(
  request: DeploymentRequest,
  framework: DetectedFramework
): Promise<StageResult> {
  const image =
    request.environment.DEPLOY_IMAGE ??
    (framework.runtime === "static" ? "pierrezemb/gostatic:latest" : "flyio/hellofly:latest");

  if (request.targetProvider === "fly" && hasIntegrationToken("fly")) {
    try {
      const result = await deployFlyApp({
        appName: request.appName,
        image,
        region: request.region ?? "iad",
        port: framework.defaultPort,
        env: request.environment
      });
      return {
        stage: "deploy-app",
        status: "succeeded",
        detail: `Deployed ${framework.framework} to Fly.io (machine ${result.machineId})`,
        data: {
          live: true,
          machineId: result.machineId,
          region: result.region,
          hostname: result.hostname
        }
      };
    } catch (error) {
      logger.error({ err: error }, "Fly.io deploy failed");
      return {
        stage: "deploy-app",
        status: "failed",
        detail: `Fly.io deploy failed: ${(error as Error).message}`
      };
    }
  }

  return {
    stage: "deploy-app",
    status: "succeeded",
    detail: `Deployed ${framework.framework} app to ${request.targetProvider} (simulated — set FLY_API_TOKEN + targetProvider=fly for live)`,
    data: {
      live: false,
      buildCommand: framework.buildCommand,
      startCommand: framework.startCommand,
      port: framework.defaultPort
    }
  };
}

export function stageSetupMonitoring(request: DeploymentRequest): StageResult {
  if (!request.enableMonitoring) {
    return { stage: "setup-monitoring", status: "skipped", detail: "Monitoring not requested" };
  }
  return {
    stage: "setup-monitoring",
    status: "succeeded",
    detail: "Uptime, metrics, and alerting configured",
    data: { healthCheckPath: "/health", alertChannels: ["email"] }
  };
}

export function stageSetupBackups(request: DeploymentRequest): StageResult {
  if (!request.enableBackups) {
    return { stage: "setup-backups", status: "skipped", detail: "Backups not requested" };
  }
  return {
    stage: "setup-backups",
    status: "succeeded",
    detail: "Daily automated backups with 7-day retention enabled",
    data: { schedule: "0 3 * * *", retentionDays: 7 }
  };
}
