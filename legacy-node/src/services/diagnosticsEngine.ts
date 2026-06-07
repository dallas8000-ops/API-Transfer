import { randomUUID } from "node:crypto";
import {
  AppliedFix,
  DiagnosisReport,
  DiagnosisRequest,
  DiagnosticIssue,
  DiagnosticSeverity,
  FixResult
} from "../domain/diagnostics";
import { DeploymentRequest, DetectedFramework } from "../domain/deployment";
import { detectFramework } from "./frameworkDetector";
import { integrityHash } from "../security/integrity";

const SECRET_KEY_PATTERN = /(secret|token|password|passwd|api[_-]?key|private[_-]?key|access[_-]?key|credential)/i;
const PLACEHOLDER_PATTERN = /^\s*(\$\{?\w+\}?|<[^>]*>|changeme|todo|x{3,}|your[_-]\S*)\s*$/i;

const SEVERITY_WEIGHT: Record<DiagnosticSeverity, number> = {
  critical: 40,
  high: 20,
  medium: 10,
  low: 4,
  info: 1
};

interface RuleContext {
  request: DiagnosisRequest;
  framework: DetectedFramework;
  scripts: Record<string, string>;
  envKeys: Set<string>;
  secretKeys: Set<string>;
  isProd: boolean;
}

type Rule = (ctx: RuleContext) => DiagnosticIssue[];

function toDeploymentRequest(request: DiagnosisRequest): DeploymentRequest {
  return {
    appName: request.appName,
    targetProvider: request.targetProvider,
    files: request.files,
    packageJson: request.packageJson,
    environment: request.environment,
    secrets: request.secrets,
    domain: request.domain,
    enableStripe: request.enableStripe,
    enableMonitoring: request.enableMonitoring,
    enableBackups: request.enableBackups,
    requestedBy: request.requestedBy,
    targetEnvironment: request.targetEnvironment
  };
}

function getScripts(packageJson?: Record<string, unknown>): Record<string, string> {
  const scripts = packageJson?.scripts;
  if (scripts && typeof scripts === "object") {
    return scripts as Record<string, string>;
  }
  return {};
}

function hasFile(files: string[], matcher: RegExp): boolean {
  return files.some((file) => matcher.test(file));
}

function isTruthyFlag(value: string): boolean {
  const v = value.trim().toLowerCase();
  return v === "true" || v === "1" || v === "on" || v === "yes";
}

// --- Rules -----------------------------------------------------------------

const nodeRules: Rule = ({ request, framework, scripts }) => {
  if (framework.runtime !== "node") return [];
  const issues: DiagnosticIssue[] = [];

  if (!request.packageJson) {
    issues.push({
      id: "node-missing-package-json",
      category: "configuration",
      severity: "critical",
      title: "package.json is missing",
      detail: "A Node.js project must include package.json for dependency installation and scripts.",
      affects: "dependency install",
      recommendation: "Add a package.json with dependencies and a start script.",
      autoFixable: false
    });
    return issues;
  }

  if (!scripts.start) {
    issues.push({
      id: "node-missing-start-script",
      category: "runtime",
      severity: "high",
      title: "No start script defined",
      detail: "package.json has no scripts.start, so the platform cannot launch the app.",
      affects: "process startup",
      recommendation: `Add a start script such as "${framework.startCommand ?? "node server.js"}".`,
      autoFixable: true,
      fix: {
        summary: "Add scripts.start to package.json",
        target: "packageJson",
        field: "scripts.start",
        suggestedValue: framework.startCommand ?? "node server.js"
      }
    });
  }

  if (!scripts.build && framework.buildCommand) {
    issues.push({
      id: "node-missing-build-script",
      category: "configuration",
      severity: "medium",
      title: "No build script defined",
      detail: "A build step is recommended for this framework but scripts.build is absent.",
      affects: "build stage",
      recommendation: `Add a build script such as "${framework.buildCommand}".`,
      autoFixable: true,
      fix: {
        summary: "Add scripts.build to package.json",
        target: "packageJson",
        field: "scripts.build",
        suggestedValue: framework.buildCommand
      }
    });
  }

  if (!request.packageJson.engines) {
    issues.push({
      id: "node-missing-engines",
      category: "configuration",
      severity: "low",
      title: "Node engine version not pinned",
      detail: "Without an engines.node field, the platform may pick an unexpected Node version.",
      affects: "runtime version",
      recommendation: "Pin engines.node to a supported LTS range (e.g. >=20).",
      autoFixable: true,
      fix: {
        summary: "Pin engines.node in package.json",
        target: "packageJson",
        field: "engines.node",
        suggestedValue: ">=20"
      }
    });
  }

  return issues;
};

const nodeEnvRule: Rule = ({ request, framework, isProd }) => {
  if (!isProd || framework.runtime !== "node") return [];
  if (request.environment.NODE_ENV === "production") return [];
  return [
    {
      id: "node-env-not-production",
      category: "configuration",
      severity: "medium",
      title: "NODE_ENV is not 'production'",
      detail: "Deploying to a production environment without NODE_ENV=production disables optimizations and enables debug behavior.",
      affects: "performance & security",
      recommendation: "Set NODE_ENV=production for production deployments.",
      autoFixable: true,
      fix: { summary: "Set NODE_ENV=production", target: "environment", field: "NODE_ENV", suggestedValue: "production" }
    }
  ];
};

const pythonRules: Rule = ({ request, framework, envKeys, isProd }) => {
  if (framework.runtime !== "python") return [];
  const issues: DiagnosticIssue[] = [];

  if (!hasFile(request.files, /requirements\.txt$|pyproject\.toml$|Pipfile$/i)) {
    issues.push({
      id: "python-missing-requirements",
      category: "dependency",
      severity: "high",
      title: "No Python dependency manifest",
      detail: "No requirements.txt, pyproject.toml or Pipfile was found to install dependencies.",
      affects: "dependency install",
      recommendation: "Add a requirements.txt (or pyproject.toml) listing your dependencies.",
      autoFixable: true,
      fix: { summary: "Generate a requirements.txt placeholder", target: "files", field: "requirements.txt" }
    });
  }

  const wsgiFramework = ["django", "flask", "fastapi"].includes(framework.framework);
  if (wsgiFramework && !hasFile(request.files, /Procfile$/i) && !envKeys.has("WEB_CONCURRENCY")) {
    issues.push({
      id: "python-no-prod-server",
      category: "runtime",
      severity: isProd ? "high" : "low",
      title: "No production WSGI/ASGI server configured",
      detail: "Frameworks like Django/Flask/FastAPI should run behind gunicorn or uvicorn in production, not the dev server.",
      affects: "process startup",
      recommendation: `Run via a production server such as "${framework.startCommand ?? "gunicorn app:app"}".`,
      autoFixable: true,
      fix: { summary: "Add a Procfile with a production server command", target: "files", field: "Procfile" }
    });
  }

  return issues;
};

const djangoRules: Rule = ({ request, framework, isProd }) => {
  if (framework.framework !== "django" || !isProd) return [];
  const issues: DiagnosticIssue[] = [];

  const debug = request.environment.DJANGO_DEBUG ?? request.environment.DEBUG ?? "";
  if (isTruthyFlag(debug)) {
    issues.push({
      id: "django-debug-enabled",
      category: "security",
      severity: "critical",
      title: "Django DEBUG is enabled in production",
      detail: "Running with DEBUG=True exposes stack traces, settings and secrets to end users.",
      affects: "information disclosure",
      recommendation: "Set DEBUG=False (DJANGO_DEBUG=False) for production.",
      autoFixable: true,
      fix: { summary: "Set DJANGO_DEBUG=False", target: "environment", field: "DJANGO_DEBUG", suggestedValue: "False" }
    });
  }

  const allowedHosts = (request.environment.ALLOWED_HOSTS ?? request.environment.DJANGO_ALLOWED_HOSTS ?? "").trim();
  if (allowedHosts === "" || allowedHosts === "*") {
    issues.push({
      id: "django-allowed-hosts",
      category: "security",
      severity: "high",
      title: "Django ALLOWED_HOSTS is empty or wildcard",
      detail: "An empty or '*' ALLOWED_HOSTS in production allows Host-header attacks and CSRF bypass.",
      affects: "host validation",
      recommendation: request.domain
        ? `Set ALLOWED_HOSTS to your domain (e.g. ${request.domain}).`
        : "Set ALLOWED_HOSTS to your specific production hostname(s).",
      autoFixable: Boolean(request.domain),
      fix: request.domain
        ? { summary: "Set ALLOWED_HOSTS to the configured domain", target: "environment", field: "ALLOWED_HOSTS", suggestedValue: request.domain }
        : undefined
    });
  }

  return issues;
};

const goRule: Rule = ({ request, framework }) => {
  if (framework.runtime !== "go" || hasFile(request.files, /go\.mod$/i)) return [];
  return [
    {
      id: "go-missing-go-mod",
      category: "dependency",
      severity: "critical",
      title: "go.mod is missing",
      detail: "A Go project must include go.mod to declare its module path and dependencies.",
      affects: "dependency resolution",
      recommendation: "Run `go mod init` and commit go.mod (and go.sum).",
      autoFixable: false
    }
  ];
};

const staticRule: Rule = ({ request, framework }) => {
  if (framework.runtime !== "static") return [];
  if (hasFile(request.files, /index\.html$/i) || hasFile(request.files, /vite\.config\.|vue\.config\./i)) return [];
  return [
    {
      id: "static-missing-entry",
      category: "configuration",
      severity: "high",
      title: "No static entry point or build config",
      detail: "A static site needs an index.html (or a build config that emits one) to serve content.",
      affects: "content serving",
      recommendation: "Ensure the build outputs an index.html, or add one at the project root.",
      autoFixable: true,
      fix: { summary: "Generate a placeholder index.html", target: "files", field: "index.html" }
    }
  ];
};

const dockerfileRule: Rule = ({ request, framework }) => {
  if (framework.framework !== "unknown" || hasFile(request.files, /^dockerfile$/i)) return [];
  return [
    {
      id: "framework-unknown",
      category: "configuration",
      severity: "high",
      title: "Framework could not be detected",
      detail: "No recognizable framework signature (config files or dependencies) was found in the project.",
      affects: "build & start commands",
      recommendation: "Add a Dockerfile or include the framework's config/entry files so the runtime can be inferred.",
      autoFixable: false
    },
    {
      id: "missing-dockerfile",
      category: "configuration",
      severity: "medium",
      title: "No Dockerfile for unrecognized runtime",
      detail: "When the framework is unknown, a Dockerfile is required to define how to build and run the app.",
      affects: "containerization",
      recommendation: "Add a Dockerfile describing the build and start commands.",
      autoFixable: true,
      fix: { summary: "Generate a starter Dockerfile", target: "files", field: "Dockerfile" }
    }
  ];
};

const portRule: Rule = ({ framework, envKeys }) => {
  if (framework.runtime === "static" || envKeys.has("PORT")) return [];
  return [
    {
      id: "missing-port-env",
      category: "networking",
      severity: "medium",
      title: "PORT environment variable not set",
      detail: "Most hosting platforms inject a PORT the app must bind to; it is not present in the configuration.",
      affects: "inbound traffic",
      recommendation: `Bind the server to process.env.PORT (default ${framework.defaultPort}).`,
      autoFixable: true,
      fix: { summary: "Add PORT to environment", target: "environment", field: "PORT", suggestedValue: String(framework.defaultPort) }
    }
  ];
};

const secretHygieneRule: Rule = ({ request }) => {
  const issues: DiagnosticIssue[] = [];
  for (const [key, value] of Object.entries(request.environment)) {
    const isPlaceholder = value === "" || PLACEHOLDER_PATTERN.test(value);
    if (SECRET_KEY_PATTERN.test(key) && value && !isPlaceholder) {
      issues.push({
        id: `plaintext-secret-${key}`,
        category: "security",
        severity: "critical",
        title: `Secret "${key}" stored as a plaintext env var`,
        detail: "Sensitive values must live in the encrypted secret store, not in plaintext environment variables.",
        affects: "secret confidentiality",
        recommendation: `Move ${key} into the encrypted secrets list and remove it from environment.`,
        autoFixable: true,
        fix: { summary: `Move ${key} from environment to encrypted secrets`, target: "secrets", field: key, suggestedValue: "[ENCRYPTED]" }
      });
    }

    if (isPlaceholder) {
      issues.push({
        id: `empty-env-${key}`,
        category: "configuration",
        severity: "medium",
        title: `Environment variable "${key}" has no real value`,
        detail: "The value is empty or a placeholder, which usually breaks the app at runtime.",
        affects: "runtime configuration",
        recommendation: `Provide a concrete value for ${key} before deploying.`,
        autoFixable: false
      });
    }
  }
  return issues;
};

const providerConfigRule: Rule = ({ request }) => {
  const providerConfig: Partial<Record<DiagnosisRequest["targetProvider"], { file: RegExp; name: string }>> = {
    fly: { file: /fly\.toml$/i, name: "fly.toml" },
    render: { file: /render\.ya?ml$/i, name: "render.yaml" },
    railway: { file: /railway\.json$|nixpacks\.toml$/i, name: "railway.json or nixpacks.toml" }
  };
  const expected = providerConfig[request.targetProvider];
  if (!expected || hasFile(request.files, expected.file)) return [];
  return [
    {
      id: `provider-config-${request.targetProvider}`,
      category: "configuration",
      severity: "low",
      title: `No ${expected.name} for ${request.targetProvider}`,
      detail: `A ${expected.name} lets you pin ${request.targetProvider} build/runtime settings instead of relying on auto-detection.`,
      affects: "deployment reproducibility",
      recommendation: `Add a ${expected.name} to make ${request.targetProvider} deployments deterministic.`,
      autoFixable: false
    }
  ];
};

const integrationRule: Rule = ({ request, envKeys, secretKeys }) => {
  const issues: DiagnosticIssue[] = [];

  if (request.enableStripe && !secretKeys.has("STRIPE_SECRET_KEY") && !envKeys.has("STRIPE_SECRET_KEY")) {
    issues.push({
      id: "stripe-missing-key",
      category: "dependency",
      severity: "high",
      title: "Stripe enabled without a secret key",
      detail: "Stripe billing is enabled but no STRIPE_SECRET_KEY is configured.",
      affects: "payments",
      recommendation: "Add STRIPE_SECRET_KEY to the encrypted secrets list.",
      autoFixable: false
    });
  }

  if (request.enableMonitoring && !envKeys.has("MONITORING_DSN") && !secretKeys.has("MONITORING_DSN")) {
    issues.push({
      id: "monitoring-missing-dsn",
      category: "observability",
      severity: "low",
      title: "Monitoring enabled without a DSN",
      detail: "Monitoring is enabled but no MONITORING_DSN endpoint is configured to receive telemetry.",
      affects: "observability",
      recommendation: "Add a MONITORING_DSN (e.g. your APM/error-tracking endpoint).",
      autoFixable: false
    });
  }

  return issues;
};

const domainRule: Rule = ({ request }) => {
  if (!request.domain || /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(request.domain)) return [];
  return [
    {
      id: "invalid-domain",
      category: "networking",
      severity: "high",
      title: "Custom domain looks malformed",
      detail: `"${request.domain}" does not look like a valid fully-qualified domain name.`,
      affects: "DNS & TLS",
      recommendation: "Use a valid FQDN such as app.example.com.",
      autoFixable: false
    }
  ];
};

const RULES: Rule[] = [
  nodeRules,
  nodeEnvRule,
  pythonRules,
  djangoRules,
  goRule,
  staticRule,
  dockerfileRule,
  portRule,
  secretHygieneRule,
  providerConfigRule,
  integrationRule,
  domainRule
];

/**
 * Inspects a project's settings and produces a deterministic, side-effect-free
 * list of configuration, security, runtime and networking issues across every
 * runtime the platform can deploy (node, python, go, static, docker).
 */
export function analyzeProject(request: DiagnosisRequest): DiagnosisReport {
  const framework = detectFramework(toDeploymentRequest(request));
  const ctx: RuleContext = {
    request,
    framework,
    scripts: getScripts(request.packageJson),
    envKeys: new Set(Object.keys(request.environment)),
    secretKeys: new Set(request.secrets.map((s) => s.key)),
    isProd: request.targetEnvironment === "prod"
  };

  const issues = RULES.flatMap((rule) => rule(ctx));
  return buildReport(request, framework, issues);
}

function buildReport(
  request: DiagnosisRequest,
  framework: DetectedFramework,
  issues: DiagnosticIssue[]
): DiagnosisReport {
  const bySeverity: Record<DiagnosticSeverity, number> = {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    info: 0
  };
  let penalty = 0;
  for (const issue of issues) {
    bySeverity[issue.severity] += 1;
    penalty += SEVERITY_WEIGHT[issue.severity];
  }

  const report: Omit<DiagnosisReport, "integrityHash"> = {
    diagnosisId: randomUUID(),
    appName: request.appName,
    framework,
    issues,
    summary: {
      total: issues.length,
      bySeverity,
      autoFixable: issues.filter((i) => i.autoFixable).length,
      healthScore: Math.max(0, 100 - penalty)
    },
    analyzedAt: new Date().toISOString()
  };

  return { ...report, integrityHash: integrityHash(report) };
}

// --- Auto-fix --------------------------------------------------------------

interface FixState {
  request: DiagnosisRequest;
  environment: Record<string, string>;
  secrets: { key: string; value: string }[];
  secretKeySet: Set<string>;
  scripts: Record<string, string>;
  packageJson: Record<string, unknown>;
  addedFiles: string[];
  applied: AppliedFix[];
  skipped: { issueId: string; reason: string }[];
}

function applyEnvironmentFix(state: FixState, issue: DiagnosticIssue): void {
  const fix = issue.fix!;
  if (fix.field && fix.suggestedValue !== undefined) {
    state.environment[fix.field] = fix.suggestedValue;
    state.applied.push(record(issue));
  } else {
    state.skipped.push({ issueId: issue.id, reason: "incomplete environment fix" });
  }
}

function applySecretFix(state: FixState, issue: DiagnosticIssue): void {
  const fix = issue.fix!;
  if (!fix.field) {
    state.skipped.push({ issueId: issue.id, reason: "missing secret key" });
    return;
  }
  const movedValue = state.request.environment[fix.field];
  if (movedValue === undefined) {
    state.skipped.push({ issueId: issue.id, reason: "source env value no longer present" });
    return;
  }
  delete state.environment[fix.field];
  if (!state.secretKeySet.has(fix.field)) {
    state.secrets.push({ key: fix.field, value: movedValue });
    state.secretKeySet.add(fix.field);
  }
  state.applied.push(record(issue));
}

function applyPackageJsonFix(state: FixState, issue: DiagnosticIssue): void {
  const fix = issue.fix!;
  if (fix.field?.startsWith("scripts.") && fix.suggestedValue) {
    state.scripts[fix.field.slice("scripts.".length)] = fix.suggestedValue;
    state.applied.push(record(issue));
  } else if (fix.field === "engines.node" && fix.suggestedValue) {
    const engines = (state.packageJson.engines as Record<string, unknown>) ?? {};
    state.packageJson.engines = { ...engines, node: fix.suggestedValue };
    state.applied.push(record(issue));
  } else {
    state.skipped.push({ issueId: issue.id, reason: "unsupported package.json field" });
  }
}

function applyFileFix(state: FixState, issue: DiagnosticIssue): void {
  const fix = issue.fix!;
  if (fix.field) {
    state.addedFiles.push(fix.field);
    state.applied.push(record(issue));
  } else {
    state.skipped.push({ issueId: issue.id, reason: "missing file name" });
  }
}

/**
 * Applies the safe, auto-fixable resolutions to produce a corrected project
 * configuration. External systems are never mutated; secrets are moved into the
 * encrypted store and never echoed in plaintext.
 */
export function applyFixes(request: DiagnosisRequest, issueIds?: string[]): FixResult {
  const report = analyzeProject(request);
  const selected = new Set(issueIds);
  const targetIssues = report.issues.filter(
    (issue) => issue.autoFixable && issue.fix && (!issueIds || selected.has(issue.id))
  );

  const state: FixState = {
    request,
    environment: { ...request.environment },
    secrets: [...request.secrets],
    secretKeySet: new Set(request.secrets.map((s) => s.key)),
    scripts: { ...getScripts(request.packageJson) },
    packageJson: request.packageJson ? { ...request.packageJson } : {},
    addedFiles: [],
    applied: [],
    skipped: []
  };

  for (const issue of targetIssues) {
    switch (issue.fix!.target) {
      case "environment":
        applyEnvironmentFix(state, issue);
        break;
      case "secrets":
        applySecretFix(state, issue);
        break;
      case "packageJson":
        applyPackageJsonFix(state, issue);
        break;
      case "files":
        applyFileFix(state, issue);
        break;
      default:
        state.skipped.push({ issueId: issue.id, reason: "unsupported fix target" });
    }
  }

  if (Object.keys(state.scripts).length > 0) {
    state.packageJson.scripts = state.scripts;
  }

  const correctedRequest: DiagnosisRequest = {
    ...request,
    environment: state.environment,
    secrets: state.secrets,
    packageJson: request.packageJson ? state.packageJson : undefined,
    files: [...request.files, ...state.addedFiles]
  };
  const residualReport = analyzeProject(correctedRequest);

  const result: Omit<FixResult, "integrityHash"> = {
    diagnosisId: report.diagnosisId,
    appName: request.appName,
    applied: state.applied,
    skipped: state.skipped,
    correctedConfig: {
      environment: state.environment,
      secretKeys: state.secrets.map((s) => s.key),
      packageJsonScripts: Object.keys(state.scripts).length > 0 ? state.scripts : undefined,
      addedFiles: state.addedFiles
    },
    residualReport
  };

  return { ...result, integrityHash: integrityHash(result) };
}

function record(issue: DiagnosticIssue): AppliedFix {
  return {
    issueId: issue.id,
    summary: issue.fix!.summary,
    target: issue.fix!.target,
    field: issue.fix!.field
  };
}
