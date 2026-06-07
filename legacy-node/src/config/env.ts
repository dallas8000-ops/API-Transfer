import "dotenv/config";
import { randomBytes } from "node:crypto";
import { z } from "zod";

const envSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  PORT: z.coerce.number().int().positive().default(4000),
  VAULT_MASTER_KEY_BASE64: z.string().optional(),
  FLY_API_TOKEN: z.string().optional(),
  FLY_API_BASE_URL: z.url().default("https://api.machines.dev"),
  FLY_ORG_SLUG: z.string().default("personal"),
  SUPABASE_ACCESS_TOKEN: z.string().optional(),
  SUPABASE_API_BASE_URL: z.url().default("https://api.supabase.com"),
  SUPABASE_ORG_ID: z.string().optional(),
  SUPABASE_DEFAULT_REGION: z.string().default("us-east-1"),
  STRIPE_SECRET_KEY: z.string().optional(),
  STRIPE_API_BASE_URL: z.url().default("https://api.stripe.com"),
  CLOUDFLARE_API_TOKEN: z.string().optional(),
  CLOUDFLARE_ZONE_ID: z.string().optional(),
  CLOUDFLARE_API_BASE_URL: z.url().default("https://api.cloudflare.com/client/v4"),
  DEPLOY_DNS_TARGET: z.string().default("203.0.113.10"),
  AUDIT_LOG_PATH: z.string().default("data/audit-log.json"),
  RBAC_ADMIN_KEYS: z.string().default(""),
  RBAC_OPERATOR_KEYS: z.string().default(""),
  RBAC_VIEWER_KEYS: z.string().default(""),
  CORS_ALLOWED_ORIGINS: z
    .string()
    .default("")
    .transform((raw) =>
      raw
        .split(",")
        .map((o) => o.trim())
        .filter((o) => o.length > 0)
    )
});

const parsed = envSchema.safeParse(process.env);
if (!parsed.success) {
  throw new Error(`Invalid environment configuration: ${parsed.error.message}`);
}

const fallbackKey = randomBytes(32).toString("base64");

if (parsed.data.NODE_ENV === "production" && !parsed.data.VAULT_MASTER_KEY_BASE64) {
  throw new Error("VAULT_MASTER_KEY_BASE64 is required in production");
}

export const env = {
  ...parsed.data,
  VAULT_MASTER_KEY_BASE64: parsed.data.VAULT_MASTER_KEY_BASE64 ?? fallbackKey
};
