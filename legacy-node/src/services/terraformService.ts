import { CanonicalMigrationSpec } from "../domain/types";
import { integrityHash } from "../security/integrity";

export type AttributeValue = string | number | boolean;

export interface TerraformResource {
  type: string;
  name: string;
  attributes: Record<string, AttributeValue>;
}

export type DriftKind = "create" | "update" | "delete" | "no-change";

export interface ResourceDrift {
  address: string;
  kind: DriftKind;
  changedAttributes: string[];
}

export interface TerraformPlan {
  planId: string;
  desired: TerraformResource[];
  drift: ResourceDrift[];
  summary: {
    create: number;
    update: number;
    delete: number;
    noChange: number;
  };
  integrityHash: string;
}

function address(resource: Pick<TerraformResource, "type" | "name">): string {
  return `${resource.type}.${resource.name}`;
}

/**
 * Builds the desired Terraform resource set from a canonical migration spec.
 * Secrets are intentionally excluded — they are managed by the secure vault and
 * surfaced to Terraform via variables, never as plaintext attributes.
 */
export function buildDesiredResources(spec: CanonicalMigrationSpec): TerraformResource[] {
  const resources: TerraformResource[] = [];

  for (const service of spec.services) {
    resources.push({
      type: "platform_service",
      name: service.name,
      attributes: {
        runtime: service.runtime,
        region: service.region ?? "default",
        replicas: service.replicas ?? 1,
        start_command: service.startCommand ?? ""
      }
    });
  }

  for (const db of spec.databases) {
    resources.push({
      type: "platform_database",
      name: db.name,
      attributes: {
        engine: db.engine,
        version: db.version ?? "latest"
      }
    });
  }

  for (const domain of spec.domains) {
    resources.push({
      type: "platform_domain",
      name: domain.host,
      attributes: {
        host: domain.host,
        tls_required: domain.tlsRequired
      }
    });
  }

  return resources;
}

function diffAttributes(
  desired: Record<string, AttributeValue>,
  current: Record<string, AttributeValue>
): string[] {
  const keys = new Set([...Object.keys(desired), ...Object.keys(current)]);
  const changed: string[] = [];
  for (const key of keys) {
    if (desired[key] !== current[key]) {
      changed.push(key);
    }
  }
  return changed;
}

/**
 * Computes drift between the desired resource set and the current (live) state.
 */
export function computeDrift(desired: TerraformResource[], current: TerraformResource[]): ResourceDrift[] {
  const currentByAddress = new Map(current.map((r) => [address(r), r]));
  const desiredByAddress = new Map(desired.map((r) => [address(r), r]));
  const drift: ResourceDrift[] = [];

  for (const resource of desired) {
    const addr = address(resource);
    const existing = currentByAddress.get(addr);
    if (!existing) {
      drift.push({ address: addr, kind: "create", changedAttributes: Object.keys(resource.attributes) });
      continue;
    }
    const changed = diffAttributes(resource.attributes, existing.attributes);
    drift.push({
      address: addr,
      kind: changed.length > 0 ? "update" : "no-change",
      changedAttributes: changed
    });
  }

  for (const resource of current) {
    const addr = address(resource);
    if (!desiredByAddress.has(addr)) {
      drift.push({ address: addr, kind: "delete", changedAttributes: Object.keys(resource.attributes) });
    }
  }

  return drift;
}

export function createTerraformPlan(
  planId: string,
  spec: CanonicalMigrationSpec,
  currentState: TerraformResource[]
): TerraformPlan {
  const desired = buildDesiredResources(spec);
  const drift = computeDrift(desired, currentState);

  const summary = {
    create: drift.filter((d) => d.kind === "create").length,
    update: drift.filter((d) => d.kind === "update").length,
    delete: drift.filter((d) => d.kind === "delete").length,
    noChange: drift.filter((d) => d.kind === "no-change").length
  };

  return {
    planId,
    desired,
    drift,
    summary,
    integrityHash: integrityHash({ planId, desired, drift, summary })
  };
}

function formatAttributeValue(value: AttributeValue): string {
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  return String(value);
}

/**
 * Renders the desired resource set as deterministic Terraform HCL. Resources are
 * sorted by address so output is stable for diffing and integrity hashing.
 */
export function generateHcl(resources: TerraformResource[]): string {
  const sorted = [...resources].sort((a, b) =>
    `${a.type}.${a.name}`.localeCompare(`${b.type}.${b.name}`)
  );

  const blocks = sorted.map((resource) => {
    const attrLines = Object.entries(resource.attributes)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => `  ${key} = ${formatAttributeValue(value)}`)
      .join("\n");

    return `resource ${JSON.stringify(resource.type)} ${JSON.stringify(resource.name)} {\n${attrLines}\n}`;
  });

  return `${blocks.join("\n\n")}\n`;
}

export interface RemediationStep {
  address: string;
  action: DriftKind;
  description: string;
}

export interface ApplyTerraformResult {
  planId: string;
  hcl: string;
  steps: RemediationStep[];
  appliedState: TerraformResource[];
  integrityHash: string;
}

/**
 * Produces a remediation plan that converges current state to desired and
 * returns the resulting state plus generated HCL. This is a deterministic,
 * side-effect-free apply used to drive an external Terraform run; it never
 * embeds secrets in the generated configuration.
 */
function describeStep(kind: DriftKind, address: string, changedAttributes: string[]): string {
  if (kind === "create") {
    return `Create ${address}`;
  }
  if (kind === "update") {
    return `Update ${address} (${changedAttributes.join(", ")})`;
  }
  return `Destroy ${address}`;
}

export function applyTerraformPlan(plan: TerraformPlan): ApplyTerraformResult {
  const steps: RemediationStep[] = plan.drift
    .filter((d) => d.kind !== "no-change")
    .map((d) => ({
      address: d.address,
      action: d.kind,
      description: describeStep(d.kind, d.address, d.changedAttributes)
    }));

  // Desired set becomes the converged state once create/update drift is applied.
  const appliedState = plan.desired;
  const hcl = generateHcl(appliedState);

  return {
    planId: plan.planId,
    hcl,
    steps,
    appliedState,
    integrityHash: integrityHash({ planId: plan.planId, hcl, steps })
  };
}
