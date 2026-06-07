import { CanonicalMigrationSpec } from "../domain/types";

export interface PolicyResult {
  allowed: boolean;
  violations: string[];
}

export function evaluatePolicies(spec: CanonicalMigrationSpec): PolicyResult {
  const violations: string[] = [];

  if (spec.metadata.environment === "prod" && spec.metadata.requestedBy.toLowerCase() === "system") {
    violations.push("Production migrations require a human requester.");
  }

  for (const service of spec.services) {
    if (service.secrets.length === 0) {
      violations.push(`Service '${service.name}' has no secrets configured.`);
    }

    if (!service.startCommand && service.runtime !== "static") {
      violations.push(`Service '${service.name}' is missing a start command.`);
    }
  }

  const insecureDomain = spec.domains.find((domain) => !domain.tlsRequired);
  if (insecureDomain) {
    violations.push(`Domain '${insecureDomain.host}' must enforce TLS.`);
  }

  return {
    allowed: violations.length === 0,
    violations
  };
}
