from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from migrationengine.providers import (
    ProviderApiError,
    _parse_github_repo,
    deploy_railway_service,
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
        strict_serial = mode == "queue" and not allow_overlap
        prefix = str(options["prefix"] or "")
        limit = max(1, min(int(options["limit"]), 100))

        if mode == "demand" and not only_values:
            raise CommandError("--mode demand requires at least one --only value.")

        self.stdout.write(self.style.NOTICE("Discovering Render services and blueprints..."))
        candidates = self._collect_candidates(limit)
        if only_values:
            candidates, unmatched = self._filter_candidates(candidates, only_values)
            for value in unmatched:
                self.stdout.write(self.style.WARNING(f"Requested target not found: {value}"))

        self.stdout.write(self.style.NOTICE(f"Mode: {mode}"))

        if not candidates:
            self.stdout.write(self.style.WARNING("No transferable Render services found."))
            return

        self.stdout.write(self.style.NOTICE(f"Found {len(candidates)} transferable service(s)."))

        successes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

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
            except ProviderApiError as exc:
                failures.append(
                    {
                        "name": railway_name,
                        "renderId": item.render_id,
                        "source": item.source,
                        "error": f"Could not read Render env vars: {exc}",
                    }
                )
                continue

            try:
                build_command, start_command, env = self._derive_deploy_config(item, env)
                result = self._deploy_with_timeout(
                    railway_name,
                    item.repo,
                    item.branch,
                    build_command,
                    start_command,
                    env,
                    item.root_directory,
                    None,
                    True,
                    service_timeout,
                )
            except ProviderApiError as exc:
                if "already exists" in str(exc).lower():
                    existing_id = get_railway_service_id_by_name(settings.RAILWAY_PROJECT_ID, railway_name)
                    if existing_id:
                        try:
                            build_command, start_command, env = self._derive_deploy_config(item, env)
                            result = self._deploy_with_timeout(
                                railway_name,
                                item.repo,
                                item.branch,
                                build_command,
                                start_command,
                                env,
                                item.root_directory,
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
                                }
                            )
                            continue
                failures.append(
                    {
                        "name": railway_name,
                        "renderId": item.render_id,
                        "source": item.source,
                        "error": str(exc),
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

        for row in failures:
            self.stdout.write(self.style.ERROR(f"FAILED {row['name']} ({row['source']}): {row['error']}"))
        for row in warnings:
            self.stdout.write(self.style.WARNING(f"WARN {row['name']} ({row['source']}): {row['message']}"))

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
        enriched["repo"] = payload.get("repo") or service.get("repo")
        enriched["branch"] = payload.get("branch") or service.get("branch")
        enriched["buildCommand"] = details.get("buildCommand") or service.get("buildCommand")
        enriched["startCommand"] = details.get("startCommand") or service.get("startCommand")
        enriched["rootDirectory"] = details.get("rootDir") or details.get("rootDirectory") or service.get("rootDirectory")
        return enriched

    def _to_candidate(self, service: dict[str, Any], source: str) -> TransferCandidate | None:
        render_id = str(service.get("id") or "").strip()
        name = str(service.get("name") or "").strip()
        repo_value = str(service.get("repo") or "").strip()

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

        return TransferCandidate(
            source=source,
            render_id=render_id,
            name=name,
            repo=repo,
            branch=str(service.get("branch") or "main"),
            build_command=service.get("buildCommand") or None,
            start_command=service.get("startCommand") or None,
            root_directory=service.get("rootDirectory") or None,
            service_type=service.get("type") or None,
            runtime=service.get("runtime") or None,
        )

    def _derive_deploy_config(
        self,
        item: TransferCandidate,
        env: dict[str, str],
    ) -> tuple[str | None, str | None, dict[str, str]]:
        build_command = item.build_command
        start_command = item.start_command
        merged_env = dict(env)

        service_type = str(item.service_type or "").strip().lower()
        runtime = str(item.runtime or "").strip().lower()

        # Static sites on Railpack need an output directory when no process start command exists.
        if service_type == "static_site":
            if "RAILPACK_SPA_OUTPUT_DIR" not in merged_env:
                output_dir = self._infer_static_output_dir(build_command)
                if output_dir:
                    merged_env["RAILPACK_SPA_OUTPUT_DIR"] = output_dir
            return build_command, None, merged_env

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

        return build_command, start_command, merged_env

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
