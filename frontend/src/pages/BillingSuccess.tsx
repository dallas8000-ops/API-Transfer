import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

export function BillingSuccess() {
  const [params] = useSearchParams();
  const sessionId = params.get("session_id");
  const [seconds, setSeconds] = useState(5);

  useEffect(() => {
    if (seconds <= 0) {
      window.location.href = "/console";
      return;
    }
    const t = setTimeout(() => setSeconds((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [seconds]);

  return (
    <div className="success">
      <div className="success-card">
        <div className="check" aria-hidden>
          OK
        </div>
        <h1>You're subscribed</h1>
        <p className="muted">
          Thanks for upgrading. Your subscription is being activated while Stripe confirms the payment.
        </p>
        {sessionId && <p className="session muted">Checkout session: {sessionId}</p>}
        <Link className="btn btn-primary" to="/console">
          Go to the Console
        </Link>
        <p className="muted small">Redirecting automatically in {seconds}s...</p>
      </div>
    </div>
  );
}
