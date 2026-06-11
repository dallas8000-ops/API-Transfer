from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import os
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from migrationengine.providers import (
    ProviderApiError,
    _parse_github_repo,
    deploy_railway_service,
    get_railway_latest_service_deployment,
    get_railway_service_id_by_name,
    get_render_env_vars,
    list_render_services,
    wait_for_railway_deployment,
)


@dataclass
class TransferCandidate:
    source: str
    render_id: str
    name: str
    repo: str
    branch: str
    build_command: str | None
    start_command: str | None
    root_directory: str | None
    service_type: str | None
    runtime: str | None


class Command(BaseCommand):
    help = "Transfer Render services (and blueprint services when available) to Railway."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            choices=["queue", "demand"],
            default="queue",
            help="Execution mode: queue runs serialized pipeline, demand targets specific services.",
        )
        parser.add_argument(
            "--only",
            action="append",
            help="Service name or Render service id to process; repeat or pass comma-separated values.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be transferred without creating Railway services.",
        )
        parser.add_argument(
            "--prefix",
            default="",
            help="Optional prefix for Railway service names (example: migrated-).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of Render services to inspect.",
        )
        parser.add_argument(
            "--no-verify",
            action="store_true",
            help="Skip post-deploy Railway status verification.",
        )
        parser.add_argument(
            "--verify-timeout",
            type=int,
            default=240,
            help="Seconds to wait per service for terminal Railway deployment status.",
        )
        parser.add_argument(
            "--verify-interval",
            type=int,
            default=10,
            help="Polling interval in seconds for Railway deployment verification.",
        )
        parser.add_argument(
            "--redeploy-existing",
            action="store_true",
            help="Trigger a new deployment for services that already exist in Railway.",
        )
        parser.add_argument(
            "--allow-overlap",
            action="store_true",
            help="Allow overlapping deployments (default behavior is serialized one-at-a-time).",
        )
        parser.add_argument(
            "--service-timeout",
            type=int,
            default=180,
            help="Hard timeout in seconds for each Railway service transfer call.",
        )
        parser.add_argument(
            "--override-root-directory",
            default="",
            help="Optional Railway root directory override (useful for monorepos).",
        )
        parser.add_argument(
            "--override-build-command",
            default="",
            help="Optional build command override for all selected services.",
        )
        parser.add_argument(
            "--override-start-command",
            default="",
            help="Optional start command override for all selected services.",
        )
        parser.add_argument(
            "--force-static-site",
            action="store_true",
            help="Treat selected services as static-site deployments (no start command).",
        )
        parser.add_argument(
            "--include-local-env-prefix",
            action="append",
            default=[],
            help="Also include local environment variables matching this prefix (repeatable, e.g. VITE_).",
        )
        parser.add_argument(
            "--include-local-env-key",
            action="append",
            default=[],
            help="Also include an exact local environment variable key (repeatable, e.g. DATABASE_URL).",
        )
        parser.add_argument(
            "--failed-only",
            action="store_true",
            help="For reruns, process only services whose latest Railway deployment is not SUCCESS.",
        )
        parser.add_argument(
            "--include-green",
            action="store_true",
            help="Disable failed-only filtering and include services that are already green.",
        )
        parser.add_argument(
            "--smoke",
            action="store_true",
            help="Run preflight + transfer + verify + readiness report in one pass.",
        )

    def handle(self, *args, **options):
        self._validate_config()

        mode = str(options["mode"])
        only_values = self._parse_only_values(options.get("only") or [])
        dry_run = bool(options["dry_run"])
        verify = not bool(options["no_verify"])
        verify_timeout = max(10, int(options["verify_timeout"]))
        verify_interval = max(3, int(options["verify_interval"]))
        redeploy_existing = bool(options["redeploy_existing"])
        allow_overlap = bool(options["allow_overlap"])
        service_timeout = max(30, int(options["service_timeout"]))
        override_root_directory = str(options.get("override_root_directory") or "").strip() or None
        override_build_command = str(options.get("override_build_command") or "").strip() or None
        override_start_command = str(options.get("override_start_command") or "").strip() or None
        force_static_site = bool(options.get("force_static_site"))
        local_env_prefixes = [
            str(prefix or "").strip()
            for prefix in (options.get("include_local_env_prefix") or [])
            if str(prefix or "").strip()
        ]
        local_env_keys = [
            str(key or "").strip()
            for key in (options.get("include_local_env_key") or [])
            if str(key or "").strip()
        ]
        smoke = bool(options.get("smoke"))
        include_green = bool(options.get("include_green"))
        failed_only = (bool(options.get("failed_only")) or redeploy_existing or smoke) and not include_green
        strict_serial = mode == "queue" and not allow_overlap
        prefix = str(options["prefix"] or "")
        limit = max(1, min(int(options["limit"]), 100))

        if smoke:
            verify = True
            redeploy_existing = True
            strict_serial = True
            self.stdout.write(self.style.NOTICE("Smoke stage: preflight"))

        if mode == "demand" and not only_values:
            raise CommandError("--mode demand requires at least one --only value.")

        self.stdout.write(self.style.NOTICE("Discovering Render services and blueprints..."))
        candidates = self._collect_candidates(limit)
        if only_values:
            candidates, unmatched = self._filter_candidates(candidates, only_values)
            for value in unmatched:
                self.stdout.write(self.style.WARNING(f"Requested target not found: {value}"))

        if failed_only:
            candidates, failed_only_skips = self._filter_failed_only_candidates(candidates, prefix)
        else:
            failed_only_skips = []

        self.stdout.write(self.style.NOTICE(f"Mode: {mode}"))

        if not candidates:
            self.stdout.write(self.style.WARNING("No transferable Render services found."))
            return

        self.stdout.write(self.style.NOTICE(f"Found {len(candidates)} transferable service(s)."))

        successes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = list(failed_only_skips)
        warnings: list[dict[str, Any]] = []

        if smoke:
            self.stdout.write(self.style.NOTICE("Smoke stage: transfer + verify"))

        for item in candidates:
            railway_name = f"{prefix}{item.name}" if prefix else item.name
            if dry_run:
                skipped.append({
                    "name": railway_name,
                    "renderId": item.render_id,
                    "source": item.source,
                    "reason": "dry-run",
                })
                self.stdout.write(f"[DRY RUN] {item.source}: {item.name} -> {railway_name}")
                continue

            self.stdout.write(f"Transferring {item.source}: {item.name} ({item.render_id})...")

            try:
                env = get_render_env_vars(item.render_id)
                if local_env_prefixes:
                    env = self._merge_local_env_vars(env, local_env_prefixes)
                if local_env_keys:
                    env = self._merge_local_env_keys(env, local_env_keys)
            except ProviderApiError as exc:
                failures.append(
                    {
                        "name": railway_name,
                        "renderId": item.render_id,
                        "source": item.source,
                        "error": f"Could not read Render env vars: {exc}",
                        "category": self._classify_provider_error(exc),
                    }
                )
                continue

            preflight_errors = self._preflight_validate_candidate(item, env)
            if preflight_errors:
                failures.append(
                    {
                        "name": railway_name,
                        "renderId": item.render_id,
                        "source": item.source,
                        "error": "Preflight failed: " + "; ".join(preflight_errors),
                        "category": "preflight",
                    }
                )
                continue

            try:
                build_command, start_command, env, root_directory = self._derive_deploy_config(
                    item,
                    env,
                    override_root_directory=override_root_directory,
                    override_build_command=override_build_command,
                    override_start_command=override_start_command,
                    force_static_site=force_static_site,
                )
                result = self._deploy_with_timeout(
                    railway_name,
                    item.repo,
                    item.branch,
                    build_command,
                    start_command,
                    env,
                    root_directory,
                    None,
                    True,
                    service_timeout,
                )
            except ProviderApiError as exc:
                if "already exists" in str(exc).lower():
                    existing_id = get_railway_service_id_by_name(settings.RAILWAY_PROJECT_ID, railway_name)
                    if existing_id:
                        try:
                            build_command, start_command, env, root_directory = self._derive_deploy_config(
                                item,
                                env,
                                override_root_directory=override_root_directory,
                                override_build_command=override_build_command,
                                override_start_command=override_start_command,
                                force_static_site=force_static_site,
                            )
                            result = self._deploy_with_timeout(
                                railway_name,
                                item.repo,
                                item.branch,
                                build_command,
                                start_command,
                                env,
                                root_directory,
                                existing_id,
                                redeploy_existing,
                                service_timeout,
                            )
                            successes.append(
                                {
                                    "name": railway_name,
                                    "renderId": item.render_id,
                                    "source": item.source,
                                    "railwayServiceId": result.get("serviceId"),
                                    "railwayDeployId": result.get("deployId"),
                                    "hostname": result.get("hostname"),
                                    "updatedExisting": True,
                                }
                            )
                            if redeploy_existing and (verify or strict_serial):
                                verification = self._verify_result(
                                    result,
                                    verify_timeout,
                                    verify_interval,
                                    strict=strict_serial,
                                )
                                if verification.get("failed"):
                                    failures.append(
                                        {
                                            "name": railway_name,
                                            "renderId": item.render_id,
                                            "source": item.source,
                                            "error": verification.get("error") or "Railway deployment failed",
                                        }
                                    )
                                    successes.pop()
                                    continue
                                if verification.get("warning"):
                                    warnings.append(
                                        {
                                            "name": railway_name,
                                            "source": item.source,
                                            "message": verification["warning"],
                                        }
                                    )
                            elif verify and not redeploy_existing:
                                warnings.append(
                                    {
                                        "name": railway_name,
                                        "source": item.source,
                                        "message": "Existing service updated without triggering a new deployment (--redeploy-existing not set).",
                                    }
                                )
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Updated existing Railway service {item.name} -> {result.get('hostname', 'railway')}"
                                )
                            )
                            continue
                        except ProviderApiError as update_exc:
                            failures.append(
                                {
                                    "name": railway_name,
                                    "renderId": item.render_id,
                                    "source": item.source,
                                    "error": str(update_exc),
                                    "category": self._classify_provider_error(update_exc),
                                }
                            )
                            continue
                failures.append(
                    {
                        "name": railway_name,
                        "renderId": item.render_id,
                        "source": item.source,
                        "error": str(exc),
                        "category": self._classify_provider_error(exc),
                    }
                )
                continue

            successes.append(
                {
                    "name": railway_name,
                    "renderId": item.render_id,
                    "source": item.source,
                    "railwayServiceId": result.get("serviceId"),
                    "railwayDeployId": result.get("deployId"),
                    "hostname": result.get("hostname"),
                }
            )
            if verify or strict_serial:
                verification = self._verify_result(
                    result,
                    verify_timeout,
                    verify_interval,
                    strict=strict_serial,
                )
                if verification.get("failed"):
                    failures.append(
                        {
                            "name": railway_name,
                            "renderId": item.render_id,
                            "source": item.source,
                            "error": verification.get("error") or "Railway deployment failed",
                            "category": "verification",
                        }
                    )
                    successes.pop()
                    continue
                if verification.get("warning"):
                    warnings.append(
                        {
                            "name": railway_name,
                            "source": item.source,
                            "message": verification["warning"],
                        }
                    )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Transferred {item.name} -> {result.get('hostname', 'railway')}")
            )

        self.stdout.write("")
        self.stdout.write(self.style.NOTICE("Transfer summary"))
        self.stdout.write(f"Succeeded: {len(successes)}")
        self.stdout.write(f"Failed: {len(failures)}")
        self.stdout.write(f"Skipped: {len(skipped)}")
        self.stdout.write(f"Warnings: {len(warnings)}")

        external_blockers = sum(1 for row in failures if row.get("category") == "external-blocker")
        preflight_failures = sum(1 for row in failures if row.get("category") == "preflight")
        if external_blockers:
            self.stdout.write(self.style.WARNING(f"External blockers: {external_blockers}"))
        if preflight_failures:
            self.stdout.write(self.style.WARNING(f"Preflight failures: {preflight_failures}"))

        for row in failures:
            self.stdout.write(self.style.ERROR(f"FAILED {row['name']} ({row['source']}): {row['error']}"))
        for row in warnings:
            self.stdout.write(self.style.WARNING(f"WARN {row['name']} ({row['source']}): {row['message']}"))

        if smoke:
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("Smoke readiness report"))
            self.stdout.write(f"Ready: {len(successes)}")
            self.stdout.write(f"Needs action: {len(failures)}")
            self.stdout.write(f"External blockers: {external_blockers}")
            self.stdout.write(f"Preflight blockers: {preflight_failures}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run mode only. Re-run without --dry-run to execute transfer."))

    def _validate_config(self) -> None:
        missing: list[str] = []
        if not settings.RENDER_API_TOKEN:
            missing.append("RENDER_API_TOKEN")
        if not settings.RAILWAY_API_TOKEN:
            missing.append("RAILWAY_API_TOKEN")
        if not settings.RAILWAY_PROJECT_ID:
            missing.append("RAILWAY_PROJECT_ID")
        if missing:
            raise CommandError(
                "Missing required configuration in .env: " + ", ".join(missing)
            )

    def _collect_candidates(self, limit: int) -> list[TransferCandidate]:
        render_services = list_render_services(limit=limit)
        by_id: dict[str, TransferCandidate] = {}

        for service in render_services:
            service = self._enrich_render_service(service)
            candidate = self._to_candidate(service, source="service")
            if candidate:
                by_id[candidate.render_id] = candidate

        for service in self._list_blueprint_services(limit=limit):
            candidate = self._to_candidate(service, source="blueprint")
            if candidate and candidate.render_id not in by_id:
                by_id[candidate.render_id] = candidate

        return sorted(by_id.values(), key=lambda item: item.name.lower())

    def _enrich_render_service(self, service: dict[str, Any]) -> dict[str, Any]:
        service_id = str(service.get("id") or "").strip()
        if not service_id:
            return service
        base = settings.RENDER_API_BASE_URL.rstrip("/")
        headers = {
            "Authorization": f"Bearer {settings.RENDER_API_TOKEN}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.get(
                f"{base}/v1/services/{service_id}",
                headers=headers,
                timeout=20,
            )
            if response.status_code != 200:
                return service
            payload_data = response.json()
            payload = payload_data if isinstance(payload_data, dict) else {}
        except (requests.RequestException, ValueError):
            return service

        details = payload.get("serviceDetails") if isinstance(payload.get("serviceDetails"), dict) else {}
        enriched = dict(service)
        enriched["repo"] = self._first_nonempty(
            (payload, service, details),
            ("repo", "repoUrl", "sourceRepo", "gitRepo"),
        )
        enriched["branch"] = self._first_nonempty((payload, service, details), ("branch",))
        enriched["buildCommand"] = self._first_nonempty((details, service, payload), ("buildCommand",))
        enriched["startCommand"] = self._first_nonempty((details, service, payload), ("startCommand",))
        enriched["rootDirectory"] = self._first_nonempty(
            (details, service, payload),
            ("rootDir", "rootDirectory", "root_directory"),
        )
        enriched["type"] = self._first_nonempty((payload, service, details), ("type",))
        enriched["runtime"] = self._first_nonempty((details, payload, service), ("runtime",))
        return enriched

    def _to_candidate(self, service: dict[str, Any], source: str) -> TransferCandidate | None:
        render_id = str(service.get("id") or "").strip()
        name = str(service.get("name") or "").strip()
        repo_value = str(self._first_nonempty((service,), ("repo", "repoUrl", "sourceRepo", "gitRepo")) or "").strip()

        self._log_render_service_fields(service, source)

        if not render_id or not name or not repo_value:
            return None

        repo = self._normalize_repo(repo_value)
        if not repo:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping {name} ({render_id}) because repo is not a GitHub URL/slug: {repo_value}"
                )
            )
            return None

        normalized_type, normalized_runtime = self._normalize_service_kind(service)

        return TransferCandidate(
            source=source,
            render_id=render_id,
            name=name,
            repo=repo,
            branch=str(service.get("branch") or "main"),
            build_command=service.get("buildCommand") or None,
            start_command=service.get("startCommand") or None,
            root_directory=self._first_nonempty((service,), ("rootDirectory", "rootDir", "root_directory")),
            service_type=normalized_type,
            runtime=normalized_runtime,
        )

    def _first_nonempty(self, sources: tuple[dict[str, Any] | None, ...], keys: tuple[str, ...]) -> Any:
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    return value
        return None

    def _log_render_service_fields(self, service: dict[str, Any], source: str) -> None:
        service_id = str(service.get("id") or "").strip() or "unknown"
        name = str(service.get("name") or "").strip() or "unknown"
        repo = self._first_nonempty((service,), ("repo", "repoUrl", "sourceRepo", "gitRepo"))
        root_directory = self._first_nonempty((service,), ("rootDirectory", "rootDir", "root_directory"))
        build_command = self._first_nonempty((service,), ("buildCommand",))
        start_command = self._first_nonempty((service,), ("startCommand",))
        runtime = self._first_nonempty((service,), ("runtime",))
        service_type = self._first_nonempty((service,), ("type",))

        discovered = []
        if repo:
            discovered.append("repo")
        if root_directory:
            discovered.append("rootDirectory")
        if build_command:
            discovered.append("buildCommand")
        if start_command:
            discovered.append("startCommand")
        if runtime:
            discovered.append("runtime")
        if service_type:
            discovered.append("type")

        missing = []
        if not repo:
            missing.append("repo")
        if not root_directory:
            missing.append("rootDirectory")
        if not build_command:
            missing.append("buildCommand")
        if not start_command:
            missing.append("startCommand")

        self.stdout.write(
            self.style.NOTICE(
                f"Render service {name} ({service_id}, {source}): discovered={','.join(discovered) or 'none'} missing={','.join(missing) or 'none'}"
            )
        )

    def _normalize_service_kind(self, service: dict[str, Any]) -> tuple[str | None, str | None]:
        raw_type = str(service.get("type") or "").strip().lower()
        runtime = str(service.get("runtime") or "").strip().lower() or None
        build_command = str(service.get("buildCommand") or "").strip().lower()
        start_command = str(service.get("startCommand") or "").strip().lower()
        name = str(service.get("name") or "").strip().lower()

        service_type = raw_type or None

        if service_type in {"static", "staticsite", "static_site"}:
            service_type = "static_site"
        elif service_type in {"web", "webservice", "web_service", "private_service", "worker"}:
            service_type = "web_service"

        if service_type is None:
            if any(token in build_command for token in ("vite", "react-scripts", "next build")) and not start_command:
                service_type = "static_site"
            elif runtime in {"node", "python", "docker"}:
                service_type = "web_service"
            elif any(token in name for token in ("-web", "frontend", "client")) and build_command and not start_command:
                service_type = "static_site"

        if runtime is None:
            if service_type == "static_site":
                runtime = "node"
            elif any(token in f"{build_command} {start_command}" for token in ("npm", "node", "vite", "next")):
                runtime = "node"
            elif any(token in f"{build_command} {start_command}" for token in ("python", "gunicorn", "uvicorn", "pip ")):
                runtime = "python"

        return service_type, runtime

    def _derive_deploy_config(
        self,
        item: TransferCandidate,
        env: dict[str, str],
        override_root_directory: str | None = None,
        override_build_command: str | None = None,
        override_start_command: str | None = None,
        force_static_site: bool = False,
    ) -> tuple[str | None, str | None, dict[str, str], str | None]:
        build_command = override_build_command or item.build_command
        start_command = override_start_command or item.start_command
        root_directory = override_root_directory or item.root_directory
        merged_env = dict(env)

        service_type = "static_site" if force_static_site else str(item.service_type or "").strip().lower()
        runtime = str(item.runtime or "").strip().lower()

        # Static sites on Railpack need an output directory when no process start command exists.
        if service_type == "static_site":
            if "RAILPACK_SPA_OUTPUT_DIR" not in merged_env:
                output_dir = self._infer_static_output_dir(build_command)
                if output_dir:
                    merged_env["RAILPACK_SPA_OUTPUT_DIR"] = output_dir
            return build_command, None, merged_env, root_directory

        if not start_command and runtime == "node":
            start_command = "npm run start --if-present || npm start || node index.js"
        elif not start_command and runtime == "python":
            start_command = (
                "gunicorn app:app --bind 0.0.0.0:$PORT || "
                "gunicorn main:app --bind 0.0.0.0:$PORT || "
                "python -m uvicorn app:app --host 0.0.0.0 --port $PORT || "
                "python -m uvicorn main:app --host 0.0.0.0 --port $PORT || "
                "python app.py || python main.py"
            )

        if runtime == "python":
            merged_env.setdefault("MISE_PYTHON_GITHUB_ATTESTATIONS", "false")
            merged_env.setdefault("MISE_PYTHON_COMPILE", "1")
            merged_env["RAILPACK_BUILD_APT_PACKAGES"] = self._merge_package_list(
                merged_env.get("RAILPACK_BUILD_APT_PACKAGES"),
                ["pkg-config", "libcairo2-dev", "python3-dev"],
            )
            merged_env["RAILPACK_DEPLOY_APT_PACKAGES"] = self._merge_package_list(
                merged_env.get("RAILPACK_DEPLOY_APT_PACKAGES"),
                ["libcairo2"],
            )

        return build_command, start_command, merged_env, root_directory

    def _merge_package_list(self, existing: str | None, required: list[str]) -> str:
        parts = [token.strip() for token in str(existing or "").split() if token.strip()]
        for token in required:
            if token not in parts:
                parts.append(token)
        return " ".join(parts)

    def _filter_failed_only_candidates(
        self,
        candidates: list[TransferCandidate],
        prefix: str,
    ) -> tuple[list[TransferCandidate], list[dict[str, Any]]]:
        remaining: list[TransferCandidate] = []
        skipped: list[dict[str, Any]] = []

        for item in candidates:
            railway_name = f"{prefix}{item.name}" if prefix else item.name
            service_id = get_railway_service_id_by_name(settings.RAILWAY_PROJECT_ID, railway_name)
            if not service_id:
                remaining.append(item)
                continue
            latest = get_railway_latest_service_deployment(settings.RAILWAY_PROJECT_ID, service_id)
            status = str((latest or {}).get("status") or "").upper()
            if status == "SUCCESS":
                skipped.append(
                    {
                        "name": railway_name,
                        "renderId": item.render_id,
                        "source": item.source,
                        "reason": "already-green",
                    }
                )
                continue
            remaining.append(item)

        return remaining, skipped

    def _preflight_validate_candidate(self, item: TransferCandidate, env: dict[str, str]) -> list[str]:
        errors: list[str] = []

        typo_keys = sorted(key for key in env if key.startswith("DJANG_") and not key.startswith("DJANGO_"))
        if typo_keys:
            errors.append("possible typo env keys: " + ", ".join(typo_keys))

        database_url = str(env.get("DATABASE_URL") or "").strip()
        if database_url:
            parsed = urlparse(database_url)
            scheme = (parsed.scheme or "").lower()
            if scheme not in {"postgres", "postgresql"}:
                errors.append("DATABASE_URL must use postgres/postgresql scheme")
            host = (parsed.hostname or "").strip().lower()
            if not host:
                errors.append("DATABASE_URL is missing hostname")
            if host.startswith("dpg-") and "." not in host:
                errors.append("DATABASE_URL uses internal Render host and is not reachable from Railway")
            if host.endswith("render.com"):
                query = {k.lower(): v for k, v in parse_qs(parsed.query or "").items()}
                ssl_mode = (query.get("sslmode") or [""])[0].lower()
                if ssl_mode != "require":
                    errors.append("DATABASE_URL for Render host must include sslmode=require")

        if item.service_type == "static_site" and not (item.build_command or "").strip():
            errors.append("static site is missing build command")

        return errors

    def _classify_provider_error(self, exc: Exception) -> str:
        text = str(exc).lower()
        if "cloudflare" in text or "attention required" in text:
            return "external-blocker"
        if "railway api error (403" in text or "not authorized" in text:
            return "external-blocker"
        return "provider"

    def _merge_local_env_vars(self, env: dict[str, str], prefixes: list[str]) -> dict[str, str]:
        merged = dict(env)
        normalized = tuple(prefixes)
        for key, value in os.environ.items():
            if any(key.startswith(prefix) for prefix in normalized):
                merged[key] = value
        return merged

    def _merge_local_env_keys(self, env: dict[str, str], keys: list[str]) -> dict[str, str]:
        merged = dict(env)
        for key in keys:
            if key in os.environ:
                merged[key] = os.environ[key]
        return merged

    def _infer_static_output_dir(self, build_command: str | None) -> str | None:
        cmd = (build_command or "").lower()
        if "react-scripts" in cmd:
            return "build"
        if "next build" in cmd:
            return ".next"
        if "vite" in cmd:
            return "dist"
        # Unknown build systems are left unset so Railway can use its own detection.
        return None

    def _verify_result(
        self,
        deploy_result: dict[str, Any],
        timeout_seconds: int,
        interval_seconds: int,
        strict: bool = False,
    ) -> dict[str, Any]:
        deployment_id = str(deploy_result.get("deployId") or "").strip()
        if not deployment_id:
            if strict:
                return {"failed": True, "error": "No deployment id was returned; cannot verify deployment outcome."}
            return {"warning": "No deployment id was returned; cannot verify deployment outcome."}

        try:
            state = wait_for_railway_deployment(
                deployment_id,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=interval_seconds,
            )
        except ProviderApiError as exc:
            if strict:
                return {"failed": True, "error": f"Could not verify deployment status: {exc}"}
            return {"warning": f"Could not verify deployment status: {exc}"}

        status = str(state.get("status") or "unknown").upper()
        if status in {"FAILED", "CRASHED", "REMOVED", "SKIPPED"}:
            diagnosis = state.get("diagnosis")
            message = f"Deployment {deployment_id} finished with status {status}."
            if diagnosis:
                message = f"{message} Diagnosis: {diagnosis}"
            return {"failed": True, "error": message}

        if state.get("timedOut"):
            if strict:
                return {
                    "failed": True,
                    "error": (
                        f"Verification timeout after {timeout_seconds}s; deployment {deployment_id} is still {status}."
                    ),
                }
            return {
                "warning": (
                    f"Verification timeout after {timeout_seconds}s; deployment {deployment_id} is still {status}."
                )
            }

        return {}

    def _deploy_with_timeout(
        self,
        app_name: str,
        repo_url: str,
        branch: str,
        build_command: str | None,
        start_command: str | None,
        env: dict[str, str],
        root_directory: str | None,
        existing_service_id: str | None,
        trigger_deploy: bool,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                deploy_railway_service,
                app_name,
                repo_url,
                branch,
                build_command,
                start_command,
                env,
                root_directory,
                existing_service_id,
                trigger_deploy,
            )
            try:
                return future.result(timeout=timeout_seconds)
            except FutureTimeoutError as exc:
                raise ProviderApiError(
                    "railway",
                    504,
                    f"Timed out after {timeout_seconds}s while transferring service '{app_name}'.",
                ) from exc

    def _normalize_repo(self, repo: str) -> str:
        value = repo.strip()
        if not value:
            return ""
        try:
            slug = _parse_github_repo(value)
        except ProviderApiError:
            return ""
        return f"https://github.com/{slug}"

    def _parse_only_values(self, raw_values: list[str]) -> set[str]:
        values: set[str] = set()
        for raw in raw_values:
            for part in str(raw).split(","):
                token = part.strip().lower()
                if token:
                    values.add(token)
        return values

    def _filter_candidates(
        self,
        candidates: list[TransferCandidate],
        only_values: set[str],
    ) -> tuple[list[TransferCandidate], list[str]]:
        filtered: list[TransferCandidate] = []
        matched: set[str] = set()
        for candidate in candidates:
            name_key = candidate.name.strip().lower()
            id_key = candidate.render_id.strip().lower()
            if name_key in only_values or id_key in only_values:
                filtered.append(candidate)
                if name_key in only_values:
                    matched.add(name_key)
                if id_key in only_values:
                    matched.add(id_key)
        unmatched = sorted(value for value in only_values if value not in matched)
        return filtered, unmatched

    def _list_blueprint_services(self, limit: int) -> list[dict[str, Any]]:
        """Best-effort expansion of Render blueprints into service-like objects.

        Render's blueprint response shape can vary. We normalize known patterns
        and ignore unknown ones without failing the transfer.
        """
        base = settings.RENDER_API_BASE_URL.rstrip("/")
        headers = {
            "Authorization": f"Bearer {settings.RENDER_API_TOKEN}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.get(
                f"{base}/v1/blueprints",
                headers=headers,
                params={"limit": limit},
                timeout=20,
            )
        except requests.RequestException:
            return []

        if response.status_code != 200:
            return []

        try:
            payload = response.json()
        except ValueError:
            return []

        rows = payload if isinstance(payload, list) else payload.get("blueprints", [])
        services: list[dict[str, Any]] = []

        for row in rows:
            if not isinstance(row, dict):
                continue
            # Pattern A: blueprint already exposes linked services.
            for svc in row.get("services", []):
                normalized = self._normalize_blueprint_service_entry(svc)
                if normalized:
                    services.append(normalized)

            # Pattern B: direct id/name/repo in the blueprint payload.
            direct = self._normalize_blueprint_service_entry(row)
            if direct:
                services.append(direct)

        return services

    def _normalize_blueprint_service_entry(self, entry: Any) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            return None
        raw = entry.get("service", entry)
        if not isinstance(raw, dict):
            return None

        details = raw.get("serviceDetails", {}) if isinstance(raw.get("serviceDetails"), dict) else {}

        svc_id = raw.get("id") or raw.get("serviceId")
        name = raw.get("name")
        repo = raw.get("repo")
        branch = raw.get("branch")

        if not svc_id or not name or not repo:
            return None

        return {
            "id": svc_id,
            "name": name,
            "repo": repo,
            "branch": branch,
            "buildCommand": details.get("buildCommand"),
            "startCommand": details.get("startCommand"),
            "rootDirectory": details.get("rootDir") or details.get("rootDirectory"),
            "type": raw.get("type") or entry.get("type"),
            "runtime": details.get("runtime"),
        }
