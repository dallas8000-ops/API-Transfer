import { CanonicalMigrationSpec } from "../domain/types";

export interface VerificationCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface VerificationReport {
  passed: boolean;
  checks: VerificationCheck[];
}

export function verifyMigration(spec: CanonicalMigrationSpec): VerificationReport {
  const checks: VerificationCheck[] = [];

  checks.push({
    name: "services-present",
    passed: spec.services.length > 0,
    detail: spec.services.length > 0 ? "At least one service defined" : "No services defined"
  });

  const allHaveStart = spec.services.every((s) => s.runtime === "static" || Boolean(s.startCommand));
  checks.push({
    name: "start-commands",
    passed: allHaveStart,
    detail: allHaveStart ? "All non-static services have start commands" : "Some services missing start commands"
  });

  const tlsEnforced = spec.domains.every((d) => d.tlsRequired);
  checks.push({
    name: "tls-enforced",
    passed: tlsEnforced,
    detail: tlsEnforced ? "All domains enforce TLS" : "One or more domains do not enforce TLS"
  });

  const secretsPresent = spec.services.every((s) => s.secrets.length > 0);
  checks.push({
    name: "secrets-configured",
    passed: secretsPresent,
    detail: secretsPresent ? "All services have secrets configured" : "Some services have no secrets"
  });

  return {
    passed: checks.every((c) => c.passed),
    checks
  };
}
