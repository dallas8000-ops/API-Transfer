import { env } from "../config/env";
import { httpJson } from "./httpClient";
import { getIntegrationToken } from "./credentials";

export interface DnsRecordInput {
  type: "A" | "CNAME";
  name: string;
  content: string;
  proxied: boolean;
}

export interface DnsRecordResult {
  id: string;
  type: string;
  name: string;
  content: string;
  proxied: boolean;
}

interface CloudflareEnvelope<T> {
  success: boolean;
  errors: unknown[];
  result: T;
}

interface CloudflareDnsRecord {
  id: string;
  type: string;
  name: string;
  content: string;
  proxied: boolean;
}

/**
 * Live Cloudflare DNS record creation. With `proxied: true`, Cloudflare also
 * provisions and serves an SSL certificate at its edge (Universal SSL),
 * satisfying the "enable SSL" stage for proxied hostnames.
 */
export async function createDnsRecord(input: DnsRecordInput): Promise<DnsRecordResult> {
  const token = getIntegrationToken("cloudflare");
  if (!token) {
    throw new Error("CLOUDFLARE_API_TOKEN is not configured");
  }
  if (!env.CLOUDFLARE_ZONE_ID) {
    throw new Error("CLOUDFLARE_ZONE_ID is not configured");
  }

  const envelope = await httpJson<CloudflareEnvelope<CloudflareDnsRecord>>("cloudflare", env.CLOUDFLARE_API_BASE_URL, {
    method: "POST",
    path: `/zones/${encodeURIComponent(env.CLOUDFLARE_ZONE_ID)}/dns_records`,
    token,
    body: {
      type: input.type,
      name: input.name,
      content: input.content,
      proxied: input.proxied,
      ttl: 1
    }
  });

  if (!envelope.success) {
    throw new Error(`Cloudflare DNS error: ${JSON.stringify(envelope.errors)}`);
  }

  return {
    id: envelope.result.id,
    type: envelope.result.type,
    name: envelope.result.name,
    content: envelope.result.content,
    proxied: envelope.result.proxied
  };
}
