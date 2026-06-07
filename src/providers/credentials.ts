import { env } from "../config/env";
import { ProviderType } from "../domain/types";

export class MissingCredentialError extends Error {
  constructor(provider: ProviderType) {
    super(`No API credential configured for provider '${provider}'. Set the corresponding token in the environment.`);
    this.name = "MissingCredentialError";
  }
}

/**
 * Resolves provider credentials from the environment. Tokens are returned only
 * to the calling client and must never be logged or persisted in plaintext.
 */
export function resolveProviderToken(provider: ProviderType): string {
  switch (provider) {
    case "fly": {
      if (!env.FLY_API_TOKEN) throw new MissingCredentialError(provider);
      return env.FLY_API_TOKEN;
    }
    case "supabase": {
      if (!env.SUPABASE_ACCESS_TOKEN) throw new MissingCredentialError(provider);
      return env.SUPABASE_ACCESS_TOKEN;
    }
    default:
      throw new MissingCredentialError(provider);
  }
}

export function hasProviderToken(provider: ProviderType): boolean {
  try {
    resolveProviderToken(provider);
    return true;
  } catch {
    return false;
  }
}

export type IntegrationId = "fly" | "stripe" | "cloudflare" | "supabase";

/**
 * Resolves credentials for deployment integrations. Returns undefined when no
 * token is configured so callers can fall back to a safe simulated path.
 * Tokens are never logged or persisted in plaintext.
 */
export function getIntegrationToken(integration: IntegrationId): string | undefined {
  switch (integration) {
    case "fly":
      return env.FLY_API_TOKEN || undefined;
    case "stripe":
      return env.STRIPE_SECRET_KEY || undefined;
    case "cloudflare":
      return env.CLOUDFLARE_API_TOKEN || undefined;
    case "supabase":
      return env.SUPABASE_ACCESS_TOKEN || undefined;
    default:
      return undefined;
  }
}

export function hasIntegrationToken(integration: IntegrationId): boolean {
  return Boolean(getIntegrationToken(integration));
}
