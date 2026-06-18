import { useEffect, useMemo, useState } from "react";
import { useDemoMode } from "../DemoModeContext";
import { getPlans, startCheckout, type Plan } from "../api";

function priceLabel(plan: Plan, currency: string): string {
  if (plan.slug === "enterprise") return "Custom";
  if (plan.priceCents === 0) return currency === "kes" ? "KES 0" : "$0";
  if (currency === "kes") {
    return `KES ${plan.price.toLocaleString("en-KE", { maximumFractionDigits: 0 })}`;
  }
  return `$${plan.price}`;
}

export function Pricing() {
  const { demoMode } = useDemoMode();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [billingEnabled, setBillingEnabled] = useState(false);
  const [paystackEnabled, setPaystackEnabled] = useState(false);
  const [currency, setCurrency] = useState<"usd" | "kes">("usd");
  const [paymentProvider, setPaymentProvider] = useState<"auto" | "stripe" | "paystack">("auto");
  const [email, setEmail] = useState("");
  const [registeredDomain, setRegisteredDomain] = useState("");
  const [loading, setLoading] = useState(true);
  const [busySlug, setBusySlug] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPlans(currency)
      .then((data) => {
        setPlans(data.plans);
        setBillingEnabled(data.billingEnabled);
        setPaystackEnabled(Boolean(data.paymentProviders?.paystack?.enabled));
        if (currency === "kes" && data.paymentProviders?.paystack?.enabled) {
          setPaymentProvider("paystack");
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [currency]);

  const emailValid = useMemo(() => /.+@.+\..+/.test(email), [email]);
  const domainValid = useMemo(
    () => /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i.test(registeredDomain.trim()),
    [registeredDomain],
  );

  async function onSelect(plan: Plan) {
    setError(null);
    if (plan.slug === "enterprise") {
      globalThis.location.href = "mailto:sales@apitransfer.dev?subject=Enterprise%20plan";
      return;
    }
    if (plan.slug === "free") {
      globalThis.location.href = "/console";
      return;
    }
    if (!emailValid) {
      setError("Enter a valid email to continue to checkout.");
      return;
    }
    if (!domainValid) {
      setError("Enter the production domain to license this instance.");
      return;
    }
    try {
      setBusySlug(plan.slug);
      const provider =
        paymentProvider === "auto" && currency === "kes" && paystackEnabled ? "paystack" : paymentProvider;
      const { url } = await startCheckout(email, plan.slug, registeredDomain.trim().toLowerCase(), 1, provider);
      if (url) {
        globalThis.location.href = url;
      } else {
        setError("Checkout session did not return a URL.");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusySlug(null);
    }
  }

  return (
    <div className="pricing">
      <section className="hero">
        <span className="eyebrow">Regional migration platform — East Africa ready</span>
        <h1>Move platforms without leaking secrets or losing control.</h1>
        <p className="lede">
          API Transfer diagnoses risky projects, builds provider-to-provider migration plans,
          protects secrets in an encrypted vault, records every privileged action, and deploys to
          Nairobi-region infrastructure with M-Pesa-ready billing.
        </p>
        <div className="hero-actions">
          <div className="row">
            <label className="inline">
              Currency{" "}
              <select value={currency} onChange={(e) => setCurrency(e.target.value as "usd" | "kes")}>
                <option value="usd">USD (Stripe)</option>
                <option value="kes">KES (Paystack / M-Pesa)</option>
              </select>
            </label>
            {paystackEnabled && (
              <label className="inline">
                Payment{" "}
                <select
                  value={paymentProvider}
                  onChange={(e) => setPaymentProvider(e.target.value as "auto" | "stripe" | "paystack")}
                >
                  <option value="auto">Auto</option>
                  <option value="paystack">Paystack</option>
                  <option value="stripe">Stripe</option>
                </select>
              </label>
            )}
          </div>
          <input
            type="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-label="Email for checkout"
          />
          <input
            type="text"
            placeholder="app.yourcompany.com"
            value={registeredDomain}
            onChange={(e) => setRegisteredDomain(e.target.value)}
            aria-label="Registered domain for license"
          />
          <span className="muted">Used for your subscription receipt and workspace ownership.</span>
          <span className="muted">Paid plans bind one active installer instance to this domain.</span>
        </div>
        {demoMode && (
          <p className="notice">Demo mode — checkout and live billing are disabled on this link.</p>
        )}
        {!demoMode && !billingEnabled && (
          <p className="notice">Billing is not configured on this server yet (Stripe or Paystack).</p>
        )}
        {error && <p className="error">{error}</p>}
      </section>

      <section className="proof-grid" aria-label="Product differentiators">
        <div>
          <strong>Nairobi-region deploys</strong>
          <span>Orena Cloud adapter targets ke-1 with compliance and latency diagnostics built in.</span>
        </div>
        <div>
          <strong>Local payments</strong>
          <span>Paystack checkout supports KES, M-Pesa, and cards alongside Stripe USD billing.</span>
        </div>
        <div>
          <strong>DPA-aware migration</strong>
          <span>Data residency, TLS, and latency rules flag US/EU defaults before you go live.</span>
        </div>
      </section>

      {loading ? (
        <p className="muted center">Loading plans...</p>
      ) : (
        <section className="plan-grid">
          {plans.map((plan) => (
            <article key={plan.slug} className={`plan-card${plan.highlighted ? " featured" : ""}`}>
              {plan.highlighted && <span className="ribbon">Most popular</span>}
              <h3>{plan.name}</h3>
              <div className="price">
                <span className="amount">{priceLabel(plan, currency)}</span>
                {plan.interval && <span className="per">/{plan.interval}</span>}
              </div>
              <p className="plan-desc">{plan.description}</p>
              <ul className="features">
                {plan.features.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              <button
                className={`btn ${plan.highlighted ? "btn-primary" : "btn-outline"} btn-block`}
                disabled={busySlug !== null || (plan.purchasable && !billingEnabled)}
                onClick={() => onSelect(plan)}
              >
                {busySlug === plan.slug ? "Redirecting..." : plan.cta}
              </button>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
