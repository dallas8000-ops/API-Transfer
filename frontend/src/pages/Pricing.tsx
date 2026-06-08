import { useEffect, useMemo, useState } from "react";
import { getPlans, startCheckout, type Plan } from "../api";

function priceLabel(plan: Plan): string {
  if (plan.slug === "enterprise") return "Custom";
  if (plan.priceCents === 0) return "$0";
  return `$${plan.price}`;
}

export function Pricing() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [billingEnabled, setBillingEnabled] = useState(false);
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(true);
  const [busySlug, setBusySlug] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPlans()
      .then((data) => {
        setPlans(data.plans);
        setBillingEnabled(data.billingEnabled);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const emailValid = useMemo(() => /.+@.+\..+/.test(email), [email]);

  async function onSelect(plan: Plan) {
    setError(null);
    if (plan.slug === "enterprise") {
      window.location.href = "mailto:sales@apitransfer.dev?subject=Enterprise%20plan";
      return;
    }
    if (plan.slug === "free") {
      window.location.href = "/console";
      return;
    }
    if (!emailValid) {
      setError("Enter a valid email to continue to checkout.");
      return;
    }
    try {
      setBusySlug(plan.slug);
      const { url } = await startCheckout(email, plan.slug);
      if (url) {
        window.location.href = url;
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
        <span className="eyebrow">Migration governance for real client apps</span>
        <h1>Move platforms without leaking secrets or losing control.</h1>
        <p className="lede">
          API Transfer diagnoses risky projects, builds provider-to-provider migration plans,
          protects secrets in an encrypted vault, records every privileged action, and separates
          live provider execution from safe simulation.
        </p>
        <div className="hero-actions">
          <input
            type="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-label="Email for checkout"
          />
          <span className="muted">Used for your subscription receipt and workspace ownership.</span>
        </div>
        {!billingEnabled && (
          <p className="notice">Billing is in preview on this server. Checkout requires Stripe credentials.</p>
        )}
        {error && <p className="error">{error}</p>}
      </section>

      <section className="proof-grid" aria-label="Product differentiators">
        <div>
          <strong>Secure migration automation</strong>
          <span>Risk-scored plans, rollback support and tamper-evident audit history.</span>
        </div>
        <div>
          <strong>Provider readiness</strong>
          <span>Live integrations are labeled clearly so paid users know what will mutate infrastructure.</span>
        </div>
        <div>
          <strong>Secret-safe by design</strong>
          <span>AES-256-GCM vaulting and recursive redaction keep plaintext credentials out of responses.</span>
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
                <span className="amount">{priceLabel(plan)}</span>
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
