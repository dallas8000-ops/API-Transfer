"""Project diagnostics + auto-fix engine.

Inspects a project's settings and produces a deterministic, side-effect-free
list of configuration, security, runtime and networking issues across every
runtime the platform can deploy (node, python, go, static, docker), then applies
the safe auto-fixable resolutions to produce a corrected configuration. External
systems are never mutated and secrets are never echoed in plaintext.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from core.integrity import integrity_hash
from core.regional import (
    DEFAULT_EAST_AFRICA_PROVIDER,
    DEFAULT_EAST_AFRICA_REGION,
    database_host_outside_africa,
    is_africa_region,
    is_high_latency_region,
)
from deployments.framework_detector import DetectedFramework, detect_framework

SECRET_KEY_PATTERN = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|private[_-]?key|access[_-]?key|credential)",
    re.IGNORECASE,
)
PLACEHOLDER_PATTERN = re.compile(
    r"^\s*(\$\{?\w+\}?|<[^>]*>|changeme|todo|x{3,}|your[_-]\S*)\s*$", re.IGNORECASE
)

SEVERITY_WEIGHT = {"critical": 40, "high": 20, "medium": 10, "low": 4, "info": 1}


@dataclass
class DiagnosisRequest:
    app_name: str
    target_provider: str
    files: list[str]
    environment: dict[str, str]
    secrets: list[dict[str, str]]
    target_environment: str
    requested_by: str
    package_json: dict[str, Any] | None = None
    domain: str | None = None
    region: str | None = None
    domains: list[dict[str, Any]] | None = None
    enable_stripe: bool = False
    enable_monitoring: bool = False
    enable_backups: bool = False


@dataclass
class _Ctx:
    request: DiagnosisRequest
    framework: DetectedFramework
    scripts: dict[str, str]
    env_keys: set[str]
    secret_keys: set[str]
    is_prod: bool


def _issue(**kwargs: Any) -> dict[str, Any]:
    base = {"autoFixable": False, "fix": None}
    base.update(kwargs)
    return base


def _get_scripts(package_json: dict[str, Any] | None) -> dict[str, str]:
    scripts = (package_json or {}).get("scripts")
    return dict(scripts) if isinstance(scripts, dict) else {}


def _has_file(files: list[str], pattern: str) -> bool:
    rx = re.compile(pattern, re.IGNORECASE)
    return any(rx.search(f) for f in files)


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "on", "yes"}


# --- Rules -----------------------------------------------------------------

def _node_rules(ctx: _Ctx) -> list[dict[str, Any]]:
    if ctx.framework.runtime != "node":
        return []
    request, fw, scripts = ctx.request, ctx.framework, ctx.scripts
    issues: list[dict[str, Any]] = []

    if request.package_json is None:
        return [
            _issue(
                id="node-missing-package-json",
                category="configuration",
                severity="critical",
                title="package.json is missing",
                detail="A Node.js project must include package.json for dependency installation and scripts.",
                affects="dependency install",
                recommendation="Add a package.json with dependencies and a start script.",
            )
        ]

    if not scripts.get("start"):
        issues.append(
            _issue(
                id="node-missing-start-script",
                category="runtime",
                severity="high",
                title="No start script defined",
                detail="package.json has no scripts.start, so the platform cannot launch the app.",
                affects="process startup",
                recommendation=f'Add a start script such as "{fw.start_command or "node server.js"}".',
                autoFixable=True,
                fix={
                    "summary": "Add scripts.start to package.json",
                    "target": "packageJson",
                    "field": "scripts.start",
                    "suggestedValue": fw.start_command or "node server.js",
                },
            )
        )

    if not scripts.get("build") and fw.build_command:
        issues.append(
            _issue(
                id="node-missing-build-script",
                category="configuration",
                severity="medium",
                title="No build script defined",
                detail="A build step is recommended for this framework but scripts.build is absent.",
                affects="build stage",
                recommendation=f'Add a build script such as "{fw.build_command}".',
                autoFixable=True,
                fix={
                    "summary": "Add scripts.build to package.json",
                    "target": "packageJson",
                    "field": "scripts.build",
                    "suggestedValue": fw.build_command,
                },
            )
        )

    if not request.package_json.get("engines"):
        issues.append(
            _issue(
                id="node-missing-engines",
                category="configuration",
                severity="low",
                title="Node engine version not pinned",
                detail="Without an engines.node field, the platform may pick an unexpected Node version.",
                affects="runtime version",
                recommendation="Pin engines.node to a supported LTS range (e.g. >=20).",
                autoFixable=True,
                fix={
                    "summary": "Pin engines.node in package.json",
                    "target": "packageJson",
                    "field": "engines.node",
                    "suggestedValue": ">=20",
                },
            )
        )

    return issues


def _node_env_rule(ctx: _Ctx) -> list[dict[str, Any]]:
    if not ctx.is_prod or ctx.framework.runtime != "node":
        return []
    if ctx.request.environment.get("NODE_ENV") == "production":
        return []
    return [
        _issue(
            id="node-env-not-production",
            category="configuration",
            severity="medium",
            title="NODE_ENV is not 'production'",
            detail="Deploying to production without NODE_ENV=production disables optimizations and enables debug behavior.",
            affects="performance & security",
            recommendation="Set NODE_ENV=production for production deployments.",
            autoFixable=True,
            fix={
                "summary": "Set NODE_ENV=production",
                "target": "environment",
                "field": "NODE_ENV",
                "suggestedValue": "production",
            },
        )
    ]


def _python_rules(ctx: _Ctx) -> list[dict[str, Any]]:
    if ctx.framework.runtime != "python":
        return []
    request, fw = ctx.request, ctx.framework
    issues: list[dict[str, Any]] = []

    if not _has_file(request.files, r"requirements\.txt$|pyproject\.toml$|Pipfile$"):
        issues.append(
            _issue(
                id="python-missing-requirements",
                category="dependency",
                severity="high",
                title="No Python dependency manifest",
                detail="No requirements.txt, pyproject.toml or Pipfile was found to install dependencies.",
                affects="dependency install",
                recommendation="Add a requirements.txt (or pyproject.toml) listing your dependencies.",
                autoFixable=True,
                fix={"summary": "Generate a requirements.txt placeholder", "target": "files", "field": "requirements.txt"},
            )
        )

    if fw.framework in {"django", "flask", "fastapi"} and not _has_file(request.files, r"Procfile$") and "WEB_CONCURRENCY" not in ctx.env_keys:
        issues.append(
            _issue(
                id="python-no-prod-server",
                category="runtime",
                severity="high" if ctx.is_prod else "low",
                title="No production WSGI/ASGI server configured",
                detail="Django/Flask/FastAPI should run behind gunicorn or uvicorn in production, not the dev server.",
                affects="process startup",
                recommendation=f'Run via a production server such as "{fw.start_command or "gunicorn app:app"}".',
                autoFixable=True,
                fix={"summary": "Add a Procfile with a production server command", "target": "files", "field": "Procfile"},
            )
        )

    return issues


def _django_rules(ctx: _Ctx) -> list[dict[str, Any]]:
    if ctx.framework.framework != "django" or not ctx.is_prod:
        return []
    request = ctx.request
    issues: list[dict[str, Any]] = []

    debug = request.environment.get("DJANGO_DEBUG") or request.environment.get("DEBUG") or ""
    if _is_truthy(debug):
        issues.append(
            _issue(
                id="django-debug-enabled",
                category="security",
                severity="critical",
                title="Django DEBUG is enabled in production",
                detail="Running with DEBUG=True exposes stack traces, settings and secrets to end users.",
                affects="information disclosure",
                recommendation="Set DEBUG=False (DJANGO_DEBUG=False) for production.",
                autoFixable=True,
                fix={"summary": "Set DJANGO_DEBUG=False", "target": "environment", "field": "DJANGO_DEBUG", "suggestedValue": "False"},
            )
        )

    allowed = (request.environment.get("ALLOWED_HOSTS") or request.environment.get("DJANGO_ALLOWED_HOSTS") or "").strip()
    if allowed in {"", "*"}:
        fix = None
        if request.domain:
            fix = {
                "summary": "Set ALLOWED_HOSTS to the configured domain",
                "target": "environment",
                "field": "ALLOWED_HOSTS",
                "suggestedValue": request.domain,
            }
        issues.append(
            _issue(
                id="django-allowed-hosts",
                category="security",
                severity="high",
                title="Django ALLOWED_HOSTS is empty or wildcard",
                detail="An empty or '*' ALLOWED_HOSTS in production allows Host-header attacks and CSRF bypass.",
                affects="host validation",
                recommendation=(
                    f"Set ALLOWED_HOSTS to your domain (e.g. {request.domain})."
                    if request.domain
                    else "Set ALLOWED_HOSTS to your specific production hostname(s)."
                ),
                autoFixable=bool(request.domain),
                fix=fix,
            )
        )

    return issues


def _go_rule(ctx: _Ctx) -> list[dict[str, Any]]:
    if ctx.framework.runtime != "go" or _has_file(ctx.request.files, r"go\.mod$"):
        return []
    return [
        _issue(
            id="go-missing-go-mod",
            category="dependency",
            severity="critical",
            title="go.mod is missing",
            detail="A Go project must include go.mod to declare its module path and dependencies.",
            affects="dependency resolution",
            recommendation="Run `go mod init` and commit go.mod (and go.sum).",
        )
    ]


def _static_rule(ctx: _Ctx) -> list[dict[str, Any]]:
    if ctx.framework.runtime != "static":
        return []
    if _has_file(ctx.request.files, r"index\.html$") or _has_file(ctx.request.files, r"vite\.config\.|vue\.config\."):
        return []
    return [
        _issue(
            id="static-missing-entry",
            category="configuration",
            severity="high",
            title="No static entry point or build config",
            detail="A static site needs an index.html (or a build config that emits one) to serve content.",
            affects="content serving",
            recommendation="Ensure the build outputs an index.html, or add one at the project root.",
            autoFixable=True,
            fix={"summary": "Generate a placeholder index.html", "target": "files", "field": "index.html"},
        )
    ]


def _dockerfile_rule(ctx: _Ctx) -> list[dict[str, Any]]:
    if ctx.framework.framework != "unknown" or _has_file(ctx.request.files, r"^dockerfile$"):
        return []
    return [
        _issue(
            id="framework-unknown",
            category="configuration",
            severity="high",
            title="Framework could not be detected",
            detail="No recognizable framework signature (config files or dependencies) was found in the project.",
            affects="build & start commands",
            recommendation="Add a Dockerfile or include the framework's config/entry files so the runtime can be inferred.",
        ),
        _issue(
            id="missing-dockerfile",
            category="configuration",
            severity="medium",
            title="No Dockerfile for unrecognized runtime",
            detail="When the framework is unknown, a Dockerfile is required to define how to build and run the app.",
            affects="containerization",
            recommendation="Add a Dockerfile describing the build and start commands.",
            autoFixable=True,
            fix={"summary": "Generate a starter Dockerfile", "target": "files", "field": "Dockerfile"},
        ),
    ]


def _port_rule(ctx: _Ctx) -> list[dict[str, Any]]:
    if ctx.framework.runtime == "static" or "PORT" in ctx.env_keys:
        return []
    return [
        _issue(
            id="missing-port-env",
            category="networking",
            severity="medium",
            title="PORT environment variable not set",
            detail="Most hosting platforms inject a PORT the app must bind to; it is not present in the configuration.",
            affects="inbound traffic",
            recommendation=f"Bind the server to the PORT env var (default {ctx.framework.default_port}).",
            autoFixable=True,
            fix={"summary": "Add PORT to environment", "target": "environment", "field": "PORT", "suggestedValue": str(ctx.framework.default_port)},
        )
    ]


def _secret_hygiene_rule(ctx: _Ctx) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for key, value in ctx.request.environment.items():
        is_placeholder = value == "" or bool(PLACEHOLDER_PATTERN.match(value))
        if SECRET_KEY_PATTERN.search(key) and value and not is_placeholder:
            issues.append(
                _issue(
                    id=f"plaintext-secret-{key}",
                    category="security",
                    severity="critical",
                    title=f'Secret "{key}" stored as a plaintext env var',
                    detail="Sensitive values must live in the encrypted secret store, not in plaintext environment variables.",
                    affects="secret confidentiality",
                    recommendation=f"Move {key} into the encrypted secrets list and remove it from environment.",
                    autoFixable=True,
                    fix={"summary": f"Move {key} from environment to encrypted secrets", "target": "secrets", "field": key, "suggestedValue": "[ENCRYPTED]"},
                )
            )
        if is_placeholder:
            issues.append(
                _issue(
                    id=f"empty-env-{key}",
                    category="configuration",
                    severity="medium",
                    title=f'Environment variable "{key}" has no real value',
                    detail="The value is empty or a placeholder, which usually breaks the app at runtime.",
                    affects="runtime configuration",
                    recommendation=f"Provide a concrete value for {key} before deploying.",
                )
            )
    return issues


def _provider_config_rule(ctx: _Ctx) -> list[dict[str, Any]]:
    provider_config = {
        "fly": (r"fly\.toml$", "fly.toml"),
        "render": (r"render\.ya?ml$", "render.yaml"),
        "railway": (r"railway\.json$|nixpacks\.toml$", "railway.json or nixpacks.toml"),
        "orena": (r"orena\.ya?ml$|\.orena$", "orena.yaml"),
    }
    expected = provider_config.get(ctx.request.target_provider)
    if not expected or _has_file(ctx.request.files, expected[0]):
        return []
    pattern, name = expected
    return [
        _issue(
            id=f"provider-config-{ctx.request.target_provider}",
            category="configuration",
            severity="low",
            title=f"No {name} for {ctx.request.target_provider}",
            detail=f"A {name} lets you pin {ctx.request.target_provider} build/runtime settings instead of relying on auto-detection.",
            affects="deployment reproducibility",
            recommendation=f"Add a {name} to make {ctx.request.target_provider} deployments deterministic.",
        )
    ]


def _integration_rule(ctx: _Ctx) -> list[dict[str, Any]]:
    request = ctx.request
    issues: list[dict[str, Any]] = []
    if request.enable_stripe and "STRIPE_SECRET_KEY" not in ctx.secret_keys and "STRIPE_SECRET_KEY" not in ctx.env_keys:
        issues.append(
            _issue(
                id="stripe-missing-key",
                category="dependency",
                severity="high",
                title="Stripe enabled without a secret key",
                detail="Stripe billing is enabled but no STRIPE_SECRET_KEY is configured.",
                affects="payments",
                recommendation="Add STRIPE_SECRET_KEY to the encrypted secrets list.",
            )
        )
    if request.enable_monitoring and "MONITORING_DSN" not in ctx.env_keys and "MONITORING_DSN" not in ctx.secret_keys:
        issues.append(
            _issue(
                id="monitoring-missing-dsn",
                category="observability",
                severity="low",
                title="Monitoring enabled without a DSN",
                detail="Monitoring is enabled but no MONITORING_DSN endpoint is configured to receive telemetry.",
                affects="observability",
                recommendation="Add a MONITORING_DSN (e.g. your APM/error-tracking endpoint).",
            )
        )
    return issues


def _domain_rule(ctx: _Ctx) -> list[dict[str, Any]]:
    domain = ctx.request.domain
    if not domain or re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain, re.IGNORECASE):
        return []
    return [
        _issue(
            id="invalid-domain",
            category="networking",
            severity="high",
            title="Custom domain looks malformed",
            detail=f'"{domain}" does not look like a valid fully-qualified domain name.',
            affects="DNS & TLS",
            recommendation="Use a valid FQDN such as app.example.com.",
        )
    ]


def _regional_compliance_rule(ctx: _Ctx) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    request = ctx.request
    region = (request.region or "").strip()
    target = request.target_provider

    if ctx.is_prod and is_high_latency_region(region) and target != DEFAULT_EAST_AFRICA_PROVIDER:
        issues.append(
            _issue(
                id="regional-latency-us-eu",
                category="compliance",
                severity="high",
                title="Production region adds latency for East Africa users",
                detail=f'Region "{region}" on {target} increases round-trip time for Kenya/Tanzania/Uganda users versus Nairobi hosting.',
                affects="latency & user experience",
                recommendation=f'Migrate compute to {DEFAULT_EAST_AFRICA_PROVIDER} ({DEFAULT_EAST_AFRICA_REGION}) or af-south-1.',
                autoFixable=True,
                fix={
                    "summary": f"Retarget deploy to {DEFAULT_EAST_AFRICA_PROVIDER}",
                    "target": "provider",
                    "field": "targetProvider",
                    "suggestedValue": DEFAULT_EAST_AFRICA_PROVIDER,
                },
            )
        )

    db_url = request.environment.get("DATABASE_URL") or request.environment.get("DB_HOST") or ""
    if ctx.is_prod and database_host_outside_africa(db_url):
        issues.append(
            _issue(
                id="regional-data-residency-db",
                category="compliance",
                severity="high",
                title="Database host appears outside Africa",
                detail="Primary database endpoints in US/EU regions may conflict with Kenya DPA 2019 data-localization expectations.",
                affects="data residency & compliance",
                recommendation=f"Provision Postgres in {DEFAULT_EAST_AFRICA_PROVIDER} ({DEFAULT_EAST_AFRICA_REGION}) and update DATABASE_URL.",
            )
        )

    for domain in request.domains or []:
        host = domain.get("host") if isinstance(domain, dict) else str(domain)
        tls_required = domain.get("tlsRequired", True) if isinstance(domain, dict) else True
        if host and tls_required is False:
            issues.append(
                _issue(
                    id=f"tls-disabled-{host}",
                    category="compliance",
                    severity="critical",
                    title=f"TLS not required for {host}",
                    detail="Production domains should enforce HTTPS for PCI and DPA-safe transport.",
                    affects="transport security",
                    recommendation="Set tlsRequired=true and terminate TLS at the edge.",
                )
            )

    if ctx.is_prod and target == DEFAULT_EAST_AFRICA_PROVIDER and not is_africa_region(region):
        issues.append(
            _issue(
                id="orena-non-africa-region",
                category="compliance",
                severity="medium",
                title="Orena deploy not pinned to Nairobi region",
                detail=f'Region "{region or "unset"}" does not match the recommended {DEFAULT_EAST_AFRICA_REGION} Nairobi tier.',
                affects="latency",
                recommendation=f"Set region to {DEFAULT_EAST_AFRICA_REGION} for ke-1 Nairobi hosting.",
                autoFixable=True,
                fix={"summary": "Pin Nairobi region", "target": "region", "field": "region", "suggestedValue": DEFAULT_EAST_AFRICA_REGION},
            )
        )

    return issues


RULES: list[Callable[[_Ctx], list[dict[str, Any]]]] = [
    _node_rules,
    _node_env_rule,
    _python_rules,
    _django_rules,
    _go_rule,
    _static_rule,
    _dockerfile_rule,
    _port_rule,
    _secret_hygiene_rule,
    _provider_config_rule,
    _integration_rule,
    _regional_compliance_rule,
    _domain_rule,
]


def analyze_project(request: DiagnosisRequest) -> dict[str, Any]:
    framework = detect_framework(request.files, request.package_json)
    ctx = _Ctx(
        request=request,
        framework=framework,
        scripts=_get_scripts(request.package_json),
        env_keys=set(request.environment.keys()),
        secret_keys={s["key"] for s in request.secrets},
        is_prod=request.target_environment == "prod",
    )
    issues: list[dict[str, Any]] = []
    for rule in RULES:
        issues.extend(rule(ctx))
    return _build_report(request, framework, issues)


def _build_report(request: DiagnosisRequest, framework: DetectedFramework, issues: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    penalty = 0
    for issue in issues:
        by_severity[issue["severity"]] += 1
        penalty += SEVERITY_WEIGHT[issue["severity"]]

    report = {
        "diagnosisId": str(uuid.uuid4()),
        "appName": request.app_name,
        "framework": framework.to_dict(),
        "issues": issues,
        "summary": {
            "total": len(issues),
            "bySeverity": by_severity,
            "autoFixable": sum(1 for i in issues if i["autoFixable"]),
            "healthScore": max(0, 100 - penalty),
        },
        "analyzedAt": datetime.now(timezone.utc).isoformat(),
    }
    report["integrityHash"] = integrity_hash(report)
    return report


# --- Auto-fix --------------------------------------------------------------

@dataclass
class _FixState:
    request: DiagnosisRequest
    environment: dict[str, str]
    secrets: list[dict[str, str]]
    secret_key_set: set[str]
    scripts: dict[str, str]
    package_json: dict[str, Any]
    added_files: list[str] = field(default_factory=list)
    applied: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def _record(issue: dict[str, Any]) -> dict[str, Any]:
    fix = issue["fix"]
    return {"issueId": issue["id"], "summary": fix["summary"], "target": fix["target"], "field": fix.get("field")}


def _apply_environment(state: _FixState, issue: dict[str, Any]) -> None:
    fix = issue["fix"]
    if fix.get("field") and fix.get("suggestedValue") is not None:
        state.environment[fix["field"]] = fix["suggestedValue"]
        state.applied.append(_record(issue))
    else:
        state.skipped.append({"issueId": issue["id"], "reason": "incomplete environment fix"})


def _apply_secret(state: _FixState, issue: dict[str, Any]) -> None:
    fix = issue["fix"]
    field_name = fix.get("field")
    if not field_name:
        state.skipped.append({"issueId": issue["id"], "reason": "missing secret key"})
        return
    moved = state.request.environment.get(field_name)
    if moved is None:
        state.skipped.append({"issueId": issue["id"], "reason": "source env value no longer present"})
        return
    state.environment.pop(field_name, None)
    if field_name not in state.secret_key_set:
        state.secrets.append({"key": field_name, "value": moved})
        state.secret_key_set.add(field_name)
    state.applied.append(_record(issue))


def _apply_package_json(state: _FixState, issue: dict[str, Any]) -> None:
    fix = issue["fix"]
    field_name = fix.get("field") or ""
    value = fix.get("suggestedValue")
    if field_name.startswith("scripts.") and value:
        state.scripts[field_name[len("scripts."):]] = value
        state.applied.append(_record(issue))
    elif field_name == "engines.node" and value:
        engines = state.package_json.get("engines") or {}
        engines = dict(engines)
        engines["node"] = value
        state.package_json["engines"] = engines
        state.applied.append(_record(issue))
    else:
        state.skipped.append({"issueId": issue["id"], "reason": "unsupported package.json field"})


def _apply_file(state: _FixState, issue: dict[str, Any]) -> None:
    fix = issue["fix"]
    if fix.get("field"):
        state.added_files.append(fix["field"])
        state.applied.append(_record(issue))
    else:
        state.skipped.append({"issueId": issue["id"], "reason": "missing file name"})


_FIX_DISPATCH = {
    "environment": _apply_environment,
    "secrets": _apply_secret,
    "packageJson": _apply_package_json,
    "files": _apply_file,
}


def apply_fixes(request: DiagnosisRequest, issue_ids: list[str] | None = None) -> dict[str, Any]:
    report = analyze_project(request)
    selected = set(issue_ids) if issue_ids is not None else None
    targets = [
        i
        for i in report["issues"]
        if i["autoFixable"] and i["fix"] and (selected is None or i["id"] in selected)
    ]

    state = _FixState(
        request=request,
        environment=dict(request.environment),
        secrets=list(request.secrets),
        secret_key_set={s["key"] for s in request.secrets},
        scripts=dict(_get_scripts(request.package_json)),
        package_json=dict(request.package_json) if request.package_json else {},
    )

    for issue in targets:
        handler = _FIX_DISPATCH.get(issue["fix"]["target"])
        if handler is None:
            state.skipped.append({"issueId": issue["id"], "reason": "unsupported fix target"})
        else:
            handler(state, issue)

    if state.scripts:
        state.package_json["scripts"] = state.scripts

    corrected = DiagnosisRequest(
        app_name=request.app_name,
        target_provider=request.target_provider,
        files=[*request.files, *state.added_files],
        environment=state.environment,
        secrets=state.secrets,
        target_environment=request.target_environment,
        requested_by=request.requested_by,
        package_json=state.package_json if request.package_json else None,
        domain=request.domain,
        enable_stripe=request.enable_stripe,
        enable_monitoring=request.enable_monitoring,
        enable_backups=request.enable_backups,
    )
    residual = analyze_project(corrected)

    result = {
        "diagnosisId": report["diagnosisId"],
        "appName": request.app_name,
        "applied": state.applied,
        "skipped": state.skipped,
        "correctedConfig": {
            "environment": state.environment,
            "secretKeys": [s["key"] for s in state.secrets],
            "packageJsonScripts": state.scripts or None,
            "addedFiles": state.added_files,
        },
        "residualReport": residual,
    }
    result["integrityHash"] = integrity_hash(result)
    return result
