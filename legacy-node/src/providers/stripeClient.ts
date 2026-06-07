import { env } from "../config/env";
import { httpForm } from "./httpClient";
import { getIntegrationToken } from "./credentials";

export interface StripeSetupInput {
  appName: string;
  productName: string;
  unitAmount: number;
  currency: string;
  webhookUrl: string;
}

export interface StripeSetupResult {
  productId: string;
  priceId: string;
  webhookId: string;
  webhookSecret: string;
}

interface StripeProduct {
  id: string;
}
interface StripePrice {
  id: string;
}
interface StripeWebhook {
  id: string;
  secret?: string;
}

/**
 * Live Stripe setup: creates a product, a recurring price, and a webhook
 * endpoint. The returned webhook signing secret is sensitive and must be
 * encrypted by the caller before storage; it is never logged here.
 */
export async function setupStripe(input: StripeSetupInput): Promise<StripeSetupResult> {
  const token = getIntegrationToken("stripe");
  if (!token) {
    throw new Error("STRIPE_SECRET_KEY is not configured");
  }

  const product = await httpForm<StripeProduct>("stripe", env.STRIPE_API_BASE_URL, {
    path: "/v1/products",
    token,
    form: { name: input.productName, metadata: { app: input.appName } }
  });

  const price = await httpForm<StripePrice>("stripe", env.STRIPE_API_BASE_URL, {
    path: "/v1/prices",
    token,
    form: {
      product: product.id,
      unit_amount: input.unitAmount,
      currency: input.currency,
      recurring: { interval: "month" }
    }
  });

  const webhook = await httpForm<StripeWebhook>("stripe", env.STRIPE_API_BASE_URL, {
    path: "/v1/webhook_endpoints",
    token,
    form: {
      url: input.webhookUrl,
      enabled_events: ["checkout.session.completed", "invoice.paid", "customer.subscription.deleted"]
    }
  });

  return {
    productId: product.id,
    priceId: price.id,
    webhookId: webhook.id,
    webhookSecret: webhook.secret ?? ""
  };
}
