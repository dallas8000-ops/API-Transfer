from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime, timezone

from django.conf import settings
from django.db.models import Count, Q
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.entitlements import (
    account_email_from_request,
    check_limit,
    entitlements_payload,
    get_or_create_workspace,
    record_usage,
)
from billing.models import ProviderConnection
from core.demo_mode import is_demo_request
from core.platform_setup import audit_platform, prewire_client, run_setup_action
from core.rbac import IsAdmin, IsOperator, IsViewer
from core.redaction import redact_sensitive_values
from deployments.framework_detector import detect_framework
from deployments.pipeline import run_pipeline

from . import adapters, planner, providers, terraform
from .audit import list_audit, record_audit, verify_chain
from .github_import import GitHubImportError, import_repository
from .models import DeploymentRun, TransferRun
from .serializers import (
    ApplyRequestSerializer,
    ClientPrewireSerializer,
    DeploymentRequestSerializer,
    GitHubImportSerializer,
    MigrationSpecSerializer,
    PlatformSetupRunSerializer,
    TransferStartSerializer,
)

_TRANSFER_LOCK = threading.Lock()
_TRANSFER_STATE: dict[str, object] = {
    "id": "",
    "process": None,
    "startedAt": "",
    "command": [],
    "logPath": "",
}

_UTC_OFFSET_SUFFIX = "+00:00"
_UTC_Z_SUFFIX = "Z"
_TRANSFER_AGING_WINDOW_DEFAULT = 300
_TRANSFER_MAX_AGING_BOOST_DEFAULT = 10


class DiscoverView(APIView):
    permission_classes = [IsViewer]

    def post(self, request):
        provider = request.data.get("provider")
        app_identifier = request.data.get("appIdentifier")
        if not provider or not app_identifier:
            return Response({"error": "provider and appIdentifier are required."}, status=400)
        if provider not in adapters.SUPPORTED_PROVIDERS:
            return Response({"error": f"Unsupported provider '{provider}'."}, status=400)

        demo_mode = is_demo_request(request)
        if demo_mode:
            result = adapters.discover_stub(provider, app_identifier)
        else:
            result = adapters.discover(provider, app_identifier)
        result["demoMode"] = demo_mode
        result["liveExecution"] = _provider_live_status(provider)
        record_audit(
            "discover",
            request.rbac_actor,
            {"provider": provider, "discoveryId": result.get("discoveryId"), "secretKeys": result.get("secretKeys", [])},
            app_identifier,
        )
        return Response(redact_sensitive_values(result))


class AccountReviewView(APIView):
    permission_classes = [IsViewer]

    def post(self, request):
        provider = request.data.get("provider")
        if not provider:
            return Response({"error": "provider is required."}, status=400)
        if provider not in adapters.ACCOUNT_REVIEW_PROVIDERS:
            return Response({"error": f"Account review is not supported for '{provider}'."}, status=400)

        result = adapters.review_account(provider)
        result["liveExecution"] = _provider_live_status(provider)
        record_audit(
            "discover",
            request.rbac_actor,
            {"provider": provider, "accountReview": True, "appCount": len(result.get("apps", []))},
            provider,
        )
        return Response(redact_sensitive_values(result))


class PlanView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        ctx = get_or_create_workspace(account_email_from_request(request))
        demo_mode = is_demo_request(request)
        limit_response = check_limit(ctx, "migration", demo_mode=demo_mode)
        if limit_response:
            return limit_response
        serializer = MigrationSpecSerializer(data=request.data.get("spec", {}))
        serializer.is_valid(raise_exception=True)
        spec = serializer.validated_data
        result = planner.generate_plan(_to_plain(spec))
        result["entitlements"] = entitlements_payload(ctx)
        record_audit("plan", request.rbac_actor, {"planId": result["plan"]["planId"]}, spec["appName"])
        record_usage(ctx, "migration", result["plan"]["planId"])
        return Response(redact_sensitive_values(result))


class ApplyView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = ApplyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        spec = _to_plain(data["spec"])
        plan = _to_plain(data["plan"])
        try:
            result = planner.apply_plan(spec, plan, data["approvedBy"])
        except (KeyError, ValueError) as exc:
            return Response({"error": str(exc)}, status=409)
        status = 200 if result["succeeded"] else 207
        record_audit("apply", request.rbac_actor, {"planId": plan["planId"], "succeeded": result["succeeded"]}, spec["appName"])
        return Response(redact_sensitive_values(result), status=status)


class RollbackView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        plan_id = request.data.get("planId")
        if not plan_id:
            return Response({"error": "planId is required."}, status=400)
        try:
            result = planner.rollback_plan(plan_id, request.rbac_actor)
        except KeyError as exc:
            return Response({"error": str(exc)}, status=404)
        record_audit("rollback", request.rbac_actor, {"restored": result["restored"]}, plan_id)
        return Response(result)


class TerraformPlanView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        serializer = MigrationSpecSerializer(data=request.data.get("spec", {}))
        serializer.is_valid(raise_exception=True)
        spec = _to_plain(serializer.validated_data)
        current_state = request.data.get("currentState", [])
        plan = terraform.create_plan(spec["appName"], spec, current_state)
        record_audit("plan", request.rbac_actor, {"terraform": True, "drift": len(plan["drift"])}, spec["appName"])
        return Response({"plan": plan})


class TerraformApplyView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        plan = request.data.get("plan")
        if not plan:
            return Response({"error": "plan is required."}, status=400)
        result = terraform.apply_plan(plan)
        record_audit("apply", request.rbac_actor, {"terraform": True, "applied": result["applied"]}, plan.get("planId", "terraform"))
        return Response({"result": result})


class DeployDetectView(APIView):
    permission_classes = [IsViewer]

    def post(self, request):
        files = request.data.get("files", [])
        package_json = request.data.get("packageJson")
        framework = detect_framework(files, package_json)
        return Response({"framework": framework.to_dict()})


class GitHubImportView(APIView):
    permission_classes = [IsViewer]

    def post(self, request):
        serializer = GitHubImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = import_repository(
                data["repoUrl"],
                branch=data.get("branch", ""),
                access_token=data.get("accessToken", ""),
            )
        except GitHubImportError as exc:
            return Response({"error": str(exc)}, status=400)
        record_audit(
            "discover",
            request.rbac_actor,
            {"source": "github", "repo": result["repository"]["fullName"], "branch": result["repository"]["branch"]},
            result["repository"]["fullName"],
        )
        return Response(redact_sensitive_values(result))


class DeployView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        ctx = get_or_create_workspace(account_email_from_request(request))
        serializer = DeploymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req = serializer.normalized()
        demo_mode = is_demo_request(request)
        req["demoMode"] = demo_mode
        live_capable = _provider_live_status(req["targetProvider"])["liveEnabled"] and not demo_mode
        if live_capable:
            limit_response = check_limit(ctx, "live_deployment", demo_mode=demo_mode)
            if limit_response:
                return limit_response
        result = run_pipeline(req)
        result["liveExecution"] = _deployment_live_summary(result)
        result["entitlements"] = entitlements_payload(ctx)
        status = 200 if result["succeeded"] else 207
        DeploymentRun.objects.create(
            deployment_id=result["deploymentId"],
            workspace=ctx.workspace,
            app_name=req["appName"],
            target_provider=req["targetProvider"],
            requested_by=req["requestedBy"],
            live=result["liveExecution"]["fullyLive"],
            succeeded=result["succeeded"],
            status=_initial_deployment_status(result),
            provider_service_id=_deploy_stage_data(result).get("serviceId") or "",
            provider_deploy_id=_deploy_stage_data(result).get("deployId") or "",
            provider_status={"initial": _deploy_stage_data(result)},
            live_url=result.get("liveUrl") or "",
            result=redact_sensitive_values(result),
        )
        record_audit("apply", request.rbac_actor, {"deploymentId": result["deploymentId"], "succeeded": result["succeeded"]}, req["appName"])
        if result["liveExecution"]["fullyLive"]:
            record_usage(ctx, "live_deployment", result["deploymentId"])
        return Response(redact_sensitive_values({"result": result}), status=status)


class AuditView(APIView):
    permission_classes = [IsViewer]

    def get(self, request):
        entries = list_audit()
        return Response({"entries": entries, "valid": verify_chain()})


class AuditExportView(APIView):
    permission_classes = [IsViewer]

    def get(self, request):
        return Response(
            {
                "exportedAt": _iso_utc_z(datetime.now(timezone.utc)),
                "entries": list_audit(),
                "chain": verify_chain(),
                "redaction": "Sensitive fields are recursively redacted before export.",
            }
        )


class ProviderStatusView(APIView):
    permission_classes = [IsViewer]

    def get(self, request):
        ctx = get_or_create_workspace(account_email_from_request(request))
        existing = {p.provider: p for p in ProviderConnection.objects.filter(workspace=ctx.workspace)}
        providers = []
        for provider in ["github", "render", "railway", "fly", "kong", "terraform", "supabase", "cloudflare", "stripe", "orena"]:
            status = _provider_live_status(provider)
            conn = existing.get(provider)
            providers.append(
                {
                    "provider": provider,
                    "liveEnabled": status["liveEnabled"],
                    "status": status["status"],
                    "capabilities": status["capabilities"],
                    "workspaceStatus": conn.status if conn else status["status"],
                    "message": status["message"],
                }
            )
        demo_mode = is_demo_request(request)
        return Response(
            {
                "providers": providers,
                "entitlements": entitlements_payload(ctx),
                "serverConfig": _server_provider_config(),
                "demoMode": demo_mode,
            }
        )


class ConsoleBootstrapView(APIView):
    """Pull provider readiness, account inventories, and workspace context in one call."""

    permission_classes = [IsViewer]

    def get(self, request):
        ctx = get_or_create_workspace(account_email_from_request(request))
        demo_mode = is_demo_request(request)
        providers = []
        account_inventories: dict[str, dict] = {}
        for provider in ["github", "render", "railway", "fly", "kong", "terraform", "supabase", "cloudflare", "stripe", "orena"]:
            status = _provider_live_status(provider)
            if demo_mode:
                status = {
                    **status,
                    "liveEnabled": False,
                    "status": "demo",
                    "message": "Demo link — live provider APIs are disabled. Use /console for production.",
                }
            providers.append({"provider": provider, **status})
            if (
                not demo_mode
                and provider in adapters.ACCOUNT_REVIEW_PROVIDERS
                and _provider_live_status(provider)["liveEnabled"]
            ):
                account_inventories[provider] = adapters.review_account(provider)

        setup_audit = audit_platform() if not demo_mode else {"summary": {"needsAttention": 0}, "tasks": []}

        return Response(
            redact_sensitive_values(
                {
                    "account": entitlements_payload(ctx),
                    "providers": providers,
                    "serverConfig": _server_provider_config(),
                    "accountInventories": account_inventories,
                    "demoMode": demo_mode,
                    "allowDemoToggle": _allow_demo_toggle(),
                    "platformSetup": setup_audit,
                }
            )
        )


class DeploymentHistoryView(APIView):
    permission_classes = [IsViewer]

    def get(self, request):
        ctx = get_or_create_workspace(account_email_from_request(request))
        limit = min(int(request.query_params.get("limit", 20)), 100)
        runs = DeploymentRun.objects.filter(workspace=ctx.workspace)[:limit]
        return Response({"runs": [r.to_dict() for r in runs]})


class DeploymentStatusRefreshView(APIView):
    permission_classes = [IsViewer]

    def post(self, request, deployment_id: str):
        ctx = get_or_create_workspace(account_email_from_request(request))
        run = DeploymentRun.objects.filter(workspace=ctx.workspace, deployment_id=deployment_id).first()
        if run is None:
            return Response({"error": "Deployment run not found."}, status=404)
        if not run.live:
            payload = {"status": "simulated", "message": "This deployment used safe simulation; no provider status is available."}
            run.mark_status("simulated", payload)
            return Response({"run": run.to_dict()})
        if run.target_provider == "render":
            if not run.provider_service_id or not run.provider_deploy_id:
                return Response({"error": "Render service/deploy identifiers were not recorded."}, status=409)
            try:
                provider_status = providers.get_render_deploy(run.provider_service_id, run.provider_deploy_id)
            except providers.ProviderApiError as exc:
                return Response({"error": str(exc)}, status=502)
            run.mark_status(_normalize_render_status(provider_status["status"]), provider_status)
            record_audit("status", request.rbac_actor, {"deploymentId": deployment_id, "provider": "render"}, run.app_name)
            return Response({"run": run.to_dict()})
        if run.target_provider == "railway":
            if not run.provider_deploy_id:
                return Response({"error": "Railway deployment identifier was not recorded."}, status=409)
            try:
                provider_status = providers.get_railway_deployment(run.provider_deploy_id)
            except providers.ProviderApiError as exc:
                return Response({"error": str(exc)}, status=502)
            run.mark_status(_normalize_railway_status(provider_status["status"]), provider_status)
            record_audit("status", request.rbac_actor, {"deploymentId": deployment_id, "provider": "railway"}, run.app_name)
            return Response({"run": run.to_dict()})
        payload = {"status": "unknown", "message": f"Status polling is not implemented for {run.target_provider} yet."}
        run.mark_status("unknown", payload)
        return Response({"run": run.to_dict()})


class TransferStartView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        serializer = TransferStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        cmd = _build_transfer_command(data)
        ctx = get_or_create_workspace(account_email_from_request(request))
        queue_only = bool(data.get("queueOnly"))
        run_id = str(uuid.uuid4())
        log_path = os.path.join(str(settings.BASE_DIR), "data", f"transfer-{run_id}.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        if queue_only:
            run = TransferRun.objects.create(
                run_id=run_id,
                workspace=ctx.workspace,
                mode=str(data.get("mode") or "queue"),
                requested_by=getattr(request, "rbac_actor", "unknown"),
                status=TransferRun.STATUS_QUEUED,
                command=cmd,
                options=_to_plain(data),
                step=TransferRun.STEP_QUEUED,
                max_retries=int(data.get("maxRetries") or 3),
                log_path=log_path,
            )
            run.mark_step(TransferRun.STEP_QUEUED, details={"queueOnly": True})
            record_audit(
                "apply",
                request.rbac_actor,
                {"kind": "transfer-queued", "runId": run_id, "mode": data.get("mode")},
                "transfer",
            )
            payload = run.to_dict()
            payload.update({"running": False, "logTail": ""})
            return Response({"run": payload})

        with _TRANSFER_LOCK:
            process = _TRANSFER_STATE.get("process")
            if isinstance(process, subprocess.Popen) and process.poll() is None:
                return Response({"error": "A transfer is already running.", "status": _transfer_status_payload()}, status=409)

            with open(log_path, "w", encoding="utf-8") as log_file:
                process = subprocess.Popen(  # noqa: S603
                    cmd,
                    cwd=str(settings.BASE_DIR),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                )

            _TRANSFER_STATE.update(
                {
                    "id": run_id,
                    "process": process,
                    "startedAt": _iso_utc_z(datetime.now(timezone.utc)),
                    "command": cmd,
                    "logPath": log_path,
                }
            )
            TransferRun.objects.create(
                run_id=run_id,
                workspace=ctx.workspace,
                mode=str(data.get("mode") or "queue"),
                requested_by=getattr(request, "rbac_actor", "unknown"),
                status=TransferRun.STATUS_RUNNING,
                command=cmd,
                options=_to_plain(data),
                step=TransferRun.STEP_TRANSFER,
                max_retries=int(data.get("maxRetries") or 3),
                attempt_started_at=datetime.now(timezone.utc),
                log_path=log_path,
            )

        record_audit(
            "apply",
            request.rbac_actor,
            {"kind": "transfer-start", "runId": run_id, "mode": data.get("mode")},
            "transfer",
        )
        return Response({"run": _transfer_status_payload()})


class TransferStopView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        with _TRANSFER_LOCK:
            process = _TRANSFER_STATE.get("process")
            if not isinstance(process, subprocess.Popen):
                return Response({"stopped": False, "message": "No transfer run is tracked."})
            if process.poll() is not None:
                return Response({"stopped": False, "message": "Transfer already finished.", "run": _transfer_status_payload()})

            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

            payload = _transfer_status_payload()

            run = TransferRun.objects.filter(run_id=payload.get("id") or "").first()
            if run is not None:
                run.status = TransferRun.STATUS_STOPPED
                run.step = TransferRun.STEP_FINALIZE
                run.exit_code = payload.get("exitCode")
                run.finished_at = datetime.now(timezone.utc)
                run.save(update_fields=["status", "step", "exit_code", "finished_at", "updated_at"])

        record_audit(
            "apply",
            request.rbac_actor,
            {"kind": "transfer-stop", "runId": payload.get("id")},
            "transfer",
        )
        return Response({"stopped": True, "run": payload})


class TransferStatusView(APIView):
    permission_classes = [IsViewer]

    def get(self, request):
        return Response({"run": _transfer_status_payload()})


class TransferHistoryView(APIView):
    permission_classes = [IsViewer]

    def get(self, request):
        raw_limit = str(request.query_params.get("limit") or "10")
        raw_cursor = str(request.query_params.get("cursor") or "").strip()
        try:
            limit = max(1, min(100, int(raw_limit)))
        except ValueError:
            return Response({"error": "limit must be an integer."}, status=400)
        cursor_id = None
        if raw_cursor:
            try:
                cursor_id = int(raw_cursor)
            except ValueError:
                return Response({"error": "cursor must be an integer id."}, status=400)

        process = _TRANSFER_STATE.get("process")
        running = isinstance(process, subprocess.Popen) and process.poll() is None
        active_run_id = str(_TRANSFER_STATE.get("id") or "")

        queryset = TransferRun.objects.order_by("-id")
        if cursor_id is not None:
            queryset = queryset.filter(id__lt=cursor_id)
        runs = list(queryset[:limit])
        payload = [_transfer_history_item(run, active_run_id, running) for run in runs]
        next_cursor = str(runs[-1].id) if len(runs) == limit else None
        return Response({"runs": payload, "nextCursor": next_cursor})


class TransferMetricsView(APIView):
    permission_classes = [IsViewer]

    def get(self, request):
        ctx = get_or_create_workspace(account_email_from_request(request))
        now = datetime.now(timezone.utc)

        running_filter = Q(status=TransferRun.STATUS_RUNNING) & Q(lease_expires_at__isnull=False) & Q(lease_expires_at__gt=now)
        queued_filter = Q(status=TransferRun.STATUS_QUEUED)
        retryable_filter = Q(status=TransferRun.STATUS_RETRYABLE)
        dead_letter_filter = Q(status=TransferRun.STATUS_DEAD_LETTER)

        all_runs = TransferRun.objects.all()
        workspace_runs = TransferRun.objects.filter(workspace=ctx.workspace)

        metrics = {
            "summary": {
                "running": all_runs.filter(running_filter).count(),
                "queued": all_runs.filter(queued_filter).count(),
                "retryable": all_runs.filter(retryable_filter).count(),
                "deadLetter": all_runs.filter(dead_letter_filter).count(),
                "total": all_runs.count(),
            },
            "schedulingPolicy": _transfer_scheduling_policy(),
            "alerts": _transfer_alerts(now=now),
            "workspace": {
                "id": ctx.workspace.id,
                "name": ctx.workspace.name,
                "running": workspace_runs.filter(running_filter).count(),
                "queued": workspace_runs.filter(queued_filter).count(),
                "retryable": workspace_runs.filter(retryable_filter).count(),
                "deadLetter": workspace_runs.filter(dead_letter_filter).count(),
                "total": workspace_runs.count(),
            },
            "runningByWorkspace": _workspace_metric_rows(all_runs.filter(running_filter)),
            "queuedByWorkspace": _workspace_metric_rows(all_runs.filter(queued_filter | retryable_filter)),
            "deadLetterByWorkspace": _workspace_metric_rows(all_runs.filter(dead_letter_filter)),
            "generatedAt": _iso_utc_z(now),
        }
        return Response(metrics)


class TransferReplayView(APIView):
    permission_classes = [IsOperator]

    def post(self, request, run_id: str):
        run = TransferRun.objects.filter(run_id=run_id).first()
        if run is None:
            return Response({"error": "Transfer run not found."}, status=404)
        if run.status not in {TransferRun.STATUS_FAILED, TransferRun.STATUS_DEAD_LETTER, TransferRun.STATUS_STOPPED}:
            return Response({"error": f"Run status '{run.status}' cannot be replayed."}, status=409)

        previous_status = run.status

        run.status = TransferRun.STATUS_QUEUED
        run.step = TransferRun.STEP_QUEUED
        run.retry_count = 0
        run.next_retry_at = None
        run.last_error = ""
        run.exit_code = None
        run.finished_at = None
        run.attempt_started_at = None
        run.lease_owner = ""
        run.lease_expires_at = None
        run.heartbeat_at = None
        run.save(
            update_fields=[
                "status",
                "step",
                "retry_count",
                "next_retry_at",
                "last_error",
                "exit_code",
                "finished_at",
                "attempt_started_at",
                "lease_owner",
                "lease_expires_at",
                "heartbeat_at",
                "updated_at",
            ]
        )
        run.mark_step(TransferRun.STEP_QUEUED, details={"replay": True, "requestedBy": request.rbac_actor})
        record_audit(
            "apply",
            request.rbac_actor,
            {"kind": "transfer-replay", "runId": run_id, "previousStatus": previous_status},
            "transfer",
        )

        payload = _transfer_history_item(run, active_run_id="", active_running=False)
        return Response({"run": payload})


def _build_transfer_command(options: dict) -> list[str]:
    cmd = [sys.executable, "manage.py", "transfer_render_to_railway", "--mode", str(options.get("mode", "queue"))]

    for value in options.get("only", []) or []:
        cmd.extend(["--only", str(value)])

    limit = options.get("limit")
    if limit:
        cmd.extend(["--limit", str(int(limit))])

    if options.get("redeployExisting"):
        cmd.append("--redeploy-existing")
    if not options.get("verify", True):
        cmd.append("--no-verify")

    cmd.extend(["--verify-timeout", str(int(options.get("verifyTimeout", 240)))])
    cmd.extend(["--verify-interval", str(int(options.get("verifyInterval", 10)))])
    cmd.extend(["--service-timeout", str(int(options.get("serviceTimeout", 180)))])

    if options.get("allowOverlap"):
        cmd.append("--allow-overlap")
    if options.get("dryRun"):
        cmd.append("--dry-run")

    return cmd


def _transfer_status_payload() -> dict:
    process = _TRANSFER_STATE.get("process")
    running = isinstance(process, subprocess.Popen) and process.poll() is None
    exit_code = None if running or not isinstance(process, subprocess.Popen) else process.poll()
    run_id = str(_TRANSFER_STATE.get("id") or "")
    record = _get_transfer_record(run_id)
    if record is None:
        return _transfer_fallback_payload(run_id, running, exit_code)

    _sync_transfer_record(record, running, exit_code)
    return _transfer_record_payload(record, run_id, running)


def _get_transfer_record(run_id: str) -> TransferRun | None:
    if run_id:
        return TransferRun.objects.filter(run_id=run_id).first()
    return TransferRun.objects.order_by("-created_at").first()


def _sync_transfer_record(record: TransferRun, running: bool, exit_code: int | None) -> None:
    if running:
        if record.status != TransferRun.STATUS_RUNNING:
            record.status = TransferRun.STATUS_RUNNING
            record.step = TransferRun.STEP_TRANSFER
            record.exit_code = None
            record.finished_at = None
            record.save(update_fields=["status", "step", "exit_code", "finished_at", "updated_at"])
        return

    if record.status != TransferRun.STATUS_RUNNING:
        return

    record.status = TransferRun.STATUS_SUCCEEDED if exit_code == 0 else TransferRun.STATUS_FAILED
    record.step = TransferRun.STEP_FINALIZE
    record.exit_code = exit_code
    record.finished_at = datetime.now(timezone.utc)
    record.save(update_fields=["status", "step", "exit_code", "finished_at", "updated_at"])


def _transfer_record_payload(record: TransferRun, run_id: str, running: bool) -> dict:
    payload = record.to_dict()
    payload.update(
        {
            "running": running if record.run_id == run_id else False,
            "exitCode": record.exit_code,
            "command": record.command,
            "logTail": _tail_file(record.log_path, 40),
        }
    )
    payload.update(_queue_priority_snapshot(record, datetime.now(timezone.utc)))
    return payload


def _transfer_fallback_payload(run_id: str, running: bool, exit_code: int | None) -> dict:
    return {
        "id": run_id,
        "running": running,
        "exitCode": exit_code,
        "startedAt": _TRANSFER_STATE.get("startedAt") or "",
        "command": _TRANSFER_STATE.get("command") or [],
        "logTail": _tail_file(str(_TRANSFER_STATE.get("logPath") or ""), 40),
        "status": "running" if running else "idle",
    }


def _transfer_history_item(run: TransferRun, active_run_id: str, active_running: bool) -> dict:
    item = run.to_dict()
    item["running"] = bool(active_running and run.run_id == active_run_id)
    item["command"] = run.command
    item["logTail"] = _tail_file(run.log_path, 12)
    item.update(_queue_priority_snapshot(run, datetime.now(timezone.utc)))
    return item


def _queue_priority_snapshot(run: TransferRun, now: datetime) -> dict:
    aging_window, max_aging_boost = _queue_aging_config()
    queue_priority = _queue_priority_value(run)
    queue_age_seconds = max(0, int((now - run.created_at).total_seconds()))
    queue_age_boost = min(max_aging_boost, queue_age_seconds // aging_window)
    return {
        "queuePriority": queue_priority,
        "queueAgeSeconds": queue_age_seconds,
        "queueAgeBoost": queue_age_boost,
        "queueEffectivePriority": queue_priority + queue_age_boost,
        "agingWindowSeconds": aging_window,
        "maxAgingBoost": max_aging_boost,
    }


def _queue_aging_config() -> tuple[int, int]:
    raw_window = getattr(settings, "TRANSFER_QUEUE_AGING_WINDOW_SECONDS", _TRANSFER_AGING_WINDOW_DEFAULT)
    raw_boost = getattr(settings, "TRANSFER_QUEUE_MAX_AGING_BOOST", _TRANSFER_MAX_AGING_BOOST_DEFAULT)
    try:
        aging_window = max(1, int(raw_window))
    except (TypeError, ValueError):
        aging_window = _TRANSFER_AGING_WINDOW_DEFAULT
    try:
        max_aging_boost = max(0, int(raw_boost))
    except (TypeError, ValueError):
        max_aging_boost = _TRANSFER_MAX_AGING_BOOST_DEFAULT
    return aging_window, max_aging_boost


def _transfer_scheduling_policy() -> dict:
    aging_window, max_aging_boost = _queue_aging_config()
    return {
        "workerBatchLimit": int(getattr(settings, "TRANSFER_WORKER_LIMIT", 5)),
        "pollIntervalSeconds": int(getattr(settings, "TRANSFER_WORKER_POLL_INTERVAL_SECONDS", 5)),
        "leaseTtlSeconds": int(getattr(settings, "TRANSFER_WORKER_LEASE_TTL_SECONDS", 120)),
        "heartbeatIntervalSeconds": int(getattr(settings, "TRANSFER_WORKER_HEARTBEAT_INTERVAL_SECONDS", 15)),
        "workspaceConcurrencyCap": int(getattr(settings, "TRANSFER_WORKSPACE_CONCURRENCY_CAP", 1)),
        "agingWindowSeconds": aging_window,
        "maxAgingBoost": max_aging_boost,
    }


def _transfer_alerts(now: datetime) -> dict:
    dead_letter_count = TransferRun.objects.filter(status=TransferRun.STATUS_DEAD_LETTER).count()
    retryable_count = TransferRun.objects.filter(status=TransferRun.STATUS_RETRYABLE).count()
    stale_lease_count = TransferRun.objects.filter(
        status=TransferRun.STATUS_RUNNING,
        lease_expires_at__isnull=False,
        lease_expires_at__lt=now,
    ).count()

    dead_letter_threshold = int(getattr(settings, "TRANSFER_ALERT_DEAD_LETTER_THRESHOLD", 5))
    retryable_threshold = int(getattr(settings, "TRANSFER_ALERT_RETRYABLE_THRESHOLD", 10))
    stale_lease_threshold = int(getattr(settings, "TRANSFER_ALERT_STALE_LEASE_THRESHOLD", 1))

    return {
        "deadLetter": {
            "active": dead_letter_count >= dead_letter_threshold,
            "count": dead_letter_count,
            "threshold": dead_letter_threshold,
        },
        "retryableBacklog": {
            "active": retryable_count >= retryable_threshold,
            "count": retryable_count,
            "threshold": retryable_threshold,
        },
        "staleLeases": {
            "active": stale_lease_count >= stale_lease_threshold,
            "count": stale_lease_count,
            "threshold": stale_lease_threshold,
        },
    }


def _queue_priority_value(run: TransferRun) -> int:
    value = (run.options or {}).get("queuePriority")
    if isinstance(value, int):
        return value
    return 0


def _workspace_metric_rows(queryset):
    rows = queryset.values("workspace_id", "workspace__name").annotate(count=Count("id")).order_by("workspace__name")
    return [
        {
            "workspaceId": row["workspace_id"] or 0,
            "workspaceName": row["workspace__name"] or "unassigned",
            "count": row["count"],
        }
        for row in rows
    ]


def _iso_utc_z(value: datetime) -> str:
    return value.isoformat().replace(_UTC_OFFSET_SUFFIX, _UTC_Z_SUFFIX)


def _tail_file(path: str, lines: int) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        data = handle.readlines()
    return "".join(data[-lines:]).strip()


def _allow_demo_toggle() -> bool:
    """Developers may switch live/design on /console; public demo links stay locked."""
    from django.conf import settings

    any_rbac = bool(settings.RBAC_ADMIN_KEYS or settings.RBAC_OPERATOR_KEYS or settings.RBAC_VIEWER_KEYS)
    return settings.DEBUG or not any_rbac


def _server_provider_config() -> dict:
    from django.conf import settings

    def _missing(*keys: str) -> list[str]:
        return [key for key in keys if not str(getattr(settings, key, "") or "").strip()]

    railway_missing = _missing("RAILWAY_API_TOKEN", "RAILWAY_PROJECT_ID")
    render_missing = list(_missing("RENDER_API_TOKEN"))
    render_deploy_ready = not _missing("RENDER_OWNER_ID")
    if not render_deploy_ready:
        render_missing.append("RENDER_OWNER_ID")

    return {
        "railway": {
            "configured": not railway_missing,
            "missing": railway_missing,
            "projectId": settings.RAILWAY_PROJECT_ID or None,
        },
        "render": {
            "configured": not _missing("RENDER_API_TOKEN"),
            "deployReady": render_deploy_ready,
            "missing": render_missing,
        },
        "stripe": {"configured": not _missing("STRIPE_SECRET_KEY"), "missing": _missing("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_PRO")},
        "fly": {"configured": not _missing("FLY_API_TOKEN"), "missing": _missing("FLY_API_TOKEN")},
        "supabase": {"configured": not _missing("SUPABASE_ACCESS_TOKEN", "SUPABASE_ORG_ID"), "missing": _missing("SUPABASE_ACCESS_TOKEN", "SUPABASE_ORG_ID")},
        "cloudflare": {"configured": not _missing("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ZONE_ID"), "missing": _missing("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ZONE_ID")},
        "orena": {
            "configured": not _missing("ORENA_API_TOKEN"),
            "missing": _missing("ORENA_API_TOKEN"),
            "projectId": settings.ORENA_PROJECT_ID or None,
            "defaultRegion": settings.ORENA_DEFAULT_REGION,
        },
        "paystack": {
            "configured": not _missing("PAYSTACK_SECRET_KEY", "PAYSTACK_PLAN_PRO"),
            "missing": _missing("PAYSTACK_SECRET_KEY", "PAYSTACK_PLAN_PRO"),
        },
        "vault": {"configured": bool(settings.VAULT_MASTER_KEY), "missing": [] if settings.VAULT_MASTER_KEY else ["VAULT_MASTER_KEY_BASE64"]},
    }


def _provider_live_status(provider: str) -> dict:
    from django.conf import settings

    matrix = {
        "fly": {
            "liveEnabled": bool(settings.FLY_API_TOKEN),
            "capabilities": ["discover", "deploy"],
            "message": "Live Fly.io discovery/deploy enabled when FLY_API_TOKEN is configured.",
        },
        "github": {
            "liveEnabled": True,
            "capabilities": ["repo-import", "framework-detection"],
            "message": "Public repo import works without a token; private repos use GITHUB_TOKEN or a request token.",
        },
        "supabase": {
            "liveEnabled": bool(settings.SUPABASE_ACCESS_TOKEN and settings.SUPABASE_ORG_ID),
            "capabilities": ["discover", "database"],
            "message": "Live Supabase discovery/provisioning enabled with access token and org id.",
        },
        "cloudflare": {
            "liveEnabled": bool(settings.CLOUDFLARE_API_TOKEN and settings.CLOUDFLARE_ZONE_ID),
            "capabilities": ["dns", "tls"],
            "message": "Live DNS enabled with Cloudflare token and zone id.",
        },
        "stripe": {
            "liveEnabled": bool(settings.STRIPE_SECRET_KEY),
            "capabilities": ["billing", "webhooks"],
            "message": "Live Stripe setup enabled with STRIPE_SECRET_KEY.",
        },
        "terraform": {
            "liveEnabled": True,
            "capabilities": ["plan", "apply", "drift"],
            "message": "Terraform plan/apply is deterministic inside API Transfer.",
        },
        "render": {
            "liveEnabled": bool(settings.RENDER_API_TOKEN),
            "capabilities": ["account-review", "discover", "deploy", "env-vars", "deploy-trigger"],
            "message": "Live Render account review/discovery is enabled with RENDER_API_TOKEN (deploy also needs RENDER_OWNER_ID).",
        },
        "railway": {
            "liveEnabled": bool(settings.RAILWAY_API_TOKEN and settings.RAILWAY_PROJECT_ID),
            "capabilities": ["account-review", "discover", "deploy", "env-vars", "deploy-trigger"],
            "message": "Live Railway account review/deploy is enabled when RAILWAY_API_TOKEN and RAILWAY_PROJECT_ID are configured.",
        },
        "orena": {
            "liveEnabled": bool(settings.ORENA_API_TOKEN),
            "capabilities": ["account-review", "discover", "deploy", "env-vars"],
            "message": f"Live Orena Cloud deploy/discovery enabled in {settings.ORENA_DEFAULT_REGION} (Nairobi) with ORENA_API_TOKEN.",
        },
        "kong": {
            "liveEnabled": False,
            "capabilities": ["canonical-discovery"],
            "message": "Kong is currently provider-neutral planning only.",
        },
    }
    item = matrix.get(provider, {"liveEnabled": False, "capabilities": [], "message": "Unknown provider."})
    return {
        **item,
        "status": "live" if item["liveEnabled"] else "demo",
    }


def _deployment_live_summary(result: dict) -> dict:
    stages = result.get("stages", [])
    live_stages = [s["stage"] for s in stages if s.get("data", {}).get("live") is True]
    simulated_stages = [s["stage"] for s in stages if s.get("data", {}).get("live") is False]
    return {
        "fullyLive": bool(live_stages) and not simulated_stages,
        "liveStages": live_stages,
        "simulatedStages": simulated_stages,
        "message": (
            "All provider-mutating stages ran live."
            if live_stages and not simulated_stages
            else "Some stages used safe simulation because provider credentials are not configured."
        ),
    }


def _deploy_stage_data(result: dict) -> dict:
    stage = next((s for s in result.get("stages", []) if s.get("stage") == "deploy-app"), None)
    return (stage or {}).get("data", {})


def _initial_deployment_status(result: dict) -> str:
    data = _deploy_stage_data(result)
    if not data.get("live"):
        return "simulated"
    return "queued" if data.get("deployId") else "live"


def _normalize_render_status(status: str) -> str:
    value = (status or "").strip().lower()
    if value in {"live", "succeeded", "success"}:
        return "live"
    if value in {"failed", "failure", "canceled", "cancelled"}:
        return "failed"
    if value in {"build_in_progress", "update_in_progress", "created", "queued", "pending"}:
        return "building"
    return value or "unknown"


def _normalize_railway_status(status: str) -> str:
    value = (status or "").strip().upper()
    if value in {"SUCCESS", "ACTIVE"}:
        return "live"
    if value in {"FAILED", "CRASHED", "REMOVED", "SKIPPED"}:
        return "failed"
    if value in {"BUILDING", "DEPLOYING", "QUEUED", "WAITING", "INITIALIZING"}:
        return "building"
    return (status or "unknown").lower()


def _to_plain(value):
    """Recursively convert serializer output to plain JSON-serializable data.

    DRF fields such as DateTimeField return ``datetime`` objects and nested
    serializers return ``OrderedDict``; both must be normalized before the value
    is fed to the integrity hasher (json.dumps).
    """
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class EnvInjectView(APIView):
    """Push a set of env vars directly to an existing Render or Railway service.

    Accepts:
      platform    - "render" or "railway"
      service_id  - Render service ID (srv-…) or Railway service UUID
      project_id  - Railway project UUID (required for railway)
      environment_id - Railway environment UUID (optional; auto-resolved if absent)
      env_vars    - dict of key→value pairs to set
    """

    permission_classes = [IsOperator]

    def post(self, request):
        from .providers import ProviderApiError, _railway_environment_id, set_render_env_vars, upsert_railway_vars

        platform = request.data.get("platform")
        service_id = (request.data.get("service_id") or request.data.get("serviceId") or "").strip()
        project_id = (request.data.get("project_id") or request.data.get("projectId") or "").strip()
        environment_id = (request.data.get("environment_id") or request.data.get("environmentId") or "").strip() or None
        env_vars = request.data.get("env_vars") or request.data.get("envVars") or {}

        if platform not in ("render", "railway"):
            return Response({"error": "platform must be 'render' or 'railway'"}, status=400)
        if not service_id:
            return Response({"error": "service_id is required"}, status=400)
        if not isinstance(env_vars, dict) or not env_vars:
            return Response({"error": "env_vars must be a non-empty object"}, status=400)

        try:
            if platform == "render":
                result = set_render_env_vars(service_id, env_vars)
            else:
                if not project_id:
                    return Response({"error": "project_id is required for railway"}, status=400)
                if not environment_id:
                    environment_id = _railway_environment_id(project_id)
                result = upsert_railway_vars(project_id, service_id, environment_id, env_vars)
        except ProviderApiError as exc:
            return Response({"error": str(exc)}, status=400)
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=400)

        record_audit(
            "env_inject",
            request.rbac_actor,
            {"platform": platform, "serviceId": service_id, "keys": result.get("pushed", [])},
            service_id,
        )
        return Response({
            "pushed": result.get("pushed", []),
            "platform": platform,
            "message": f"Pushed {len(result.get('pushed', []))} var(s) to {platform}",
        })


class RailwayEnvBackupView(APIView):
    """Export a JSON snapshot of all variables on a Railway service."""

    permission_classes = [IsOperator]

    def post(self, request):
        if is_demo_request(request):
            return Response(
                {"error": "Railway env backup is disabled on demo links. Use /console in Live mode."},
                status=400,
            )

        service_id = (request.data.get("service_id") or request.data.get("serviceId") or "").strip()
        service_name = (request.data.get("service_name") or request.data.get("serviceName") or "").strip()
        project_id = (request.data.get("project_id") or request.data.get("projectId") or "").strip() or None
        environment_id = (request.data.get("environment_id") or request.data.get("environmentId") or "").strip() or None
        save_to_disk = request.data.get("save_to_disk", request.data.get("saveToDisk", True))
        if isinstance(save_to_disk, str):
            save_to_disk = save_to_disk.lower() not in ("0", "false", "no")

        if not service_id:
            return Response({"error": "service_id is required"}, status=400)
        if not settings.RAILWAY_API_TOKEN:
            return Response({"error": "RAILWAY_API_TOKEN is not configured"}, status=400)

        try:
            snapshot = providers.backup_railway_env_snapshot(
                service_id,
                service_name=service_name,
                project_id=project_id,
                environment_id=environment_id,
                save_to_disk=bool(save_to_disk),
            )
        except ProviderApiError as exc:
            return Response({"error": str(exc)}, status=400)

        record_audit(
            "railway_env_backup",
            request.rbac_actor,
            {
                "serviceId": service_id,
                "serviceName": snapshot.get("serviceName"),
                "keyCount": snapshot.get("keyCount"),
                "secretKeyCount": snapshot.get("secretKeyCount"),
                "variableKeys": snapshot.get("variableKeys"),
                "backupPath": snapshot.get("backupPath"),
            },
            service_id,
        )

        return Response(
            {
                "message": (
                    f"Backed up {snapshot['keyCount']} variable(s) "
                    f"({snapshot['secretKeyCount']} secret key(s)) for {snapshot['serviceName']}."
                ),
                "serviceName": snapshot.get("serviceName"),
                "serviceId": snapshot.get("serviceId"),
                "projectId": snapshot.get("projectId"),
                "environmentId": snapshot.get("environmentId"),
                "backedUpAt": snapshot.get("backedUpAt"),
                "keyCount": snapshot.get("keyCount"),
                "secretKeyCount": snapshot.get("secretKeyCount"),
                "variableKeys": snapshot.get("variableKeys"),
                "secretKeys": snapshot.get("secretKeys"),
                "backupPath": snapshot.get("backupPath"),
                "backup": {
                    "serviceName": snapshot.get("serviceName"),
                    "serviceId": snapshot.get("serviceId"),
                    "projectId": snapshot.get("projectId"),
                    "environmentId": snapshot.get("environmentId"),
                    "backedUpAt": snapshot.get("backedUpAt"),
                    "variables": snapshot.get("variables"),
                },
            }
        )


class PlatformSetupAuditView(APIView):
    """Audit platform configuration gaps and available auto-setup actions."""

    permission_classes = [IsViewer]

    def get(self, request):
        if is_demo_request(request):
            return Response(
                {
                    "summary": {"totalTasks": 0, "ready": 0, "needsAttention": 0, "autoFixableIssues": 0},
                    "tasks": [],
                    "demoMode": True,
                    "message": "Platform setup audit is disabled on demo links. Use /console in Live mode.",
                }
            )
        scan = str(request.query_params.get("scanRailwayStripe", "")).lower() in {"1", "true", "yes"}
        return Response(redact_sensitive_values(audit_platform(scan_railway_stripe=scan)))


class PlatformSetupRunView(APIView):
    """Run a safe, idempotent platform setup action (Stripe catalog, webhooks, provider tests)."""

    permission_classes = [IsOperator]

    def post(self, request):
        if is_demo_request(request):
            return Response({"error": "Setup actions are disabled in demo mode."}, status=403)
        serializer = PlatformSetupRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action_id = serializer.validated_data["actionId"]
        apply_to_env = serializer.validated_data.get("applyToEnv")
        if apply_to_env is None:
            from core.env_file import can_auto_apply_dotenv

            apply_to_env = can_auto_apply_dotenv()
        env_vars = serializer.validated_data.get("envVars") or {}
        result = run_setup_action(
            action_id,
            apply_to_env=bool(apply_to_env),
            env_vars=env_vars if action_id == "apply_platform_env" else None,
        )
        try:
            record_audit("platform_setup", request.rbac_actor, {"actionId": action_id, "ok": result.get("ok")}, action_id)
        except ValueError:
            pass  # never fail setup after .env was already written
        return Response(redact_sensitive_values(result), status=200)


class ClientPrewireView(APIView):
    """Onboard a client workspace — prewire services, discover source app, generate migration plan."""

    permission_classes = [IsOperator]

    def post(self, request):
        if is_demo_request(request):
            return Response({"error": "Client prewire is disabled in demo mode."}, status=403)
        serializer = ClientPrewireSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        operator_email = account_email_from_request(request)
        services = data.get("services") or ["orena", "paystack", "monitoring", "backups"]
        result = prewire_client(
            operator_email=operator_email,
            client_email=data["clientEmail"],
            client_name=data.get("clientName") or f"{data['clientEmail']} workspace",
            client_domain=data["clientDomain"].strip().lower(),
            target_provider=data.get("targetProvider") or "orena",
            target_region=data.get("targetRegion") or "ke-1",
            source_provider=data.get("sourceProvider") or "",
            app_identifier=data.get("appIdentifier") or "",
            services=services,
            run_discover=bool(data.get("runDiscover", True)),
        )
        record_audit(
            "client_prewire",
            request.rbac_actor,
            {
                "clientEmail": data["clientEmail"],
                "clientDomain": data["clientDomain"],
                "ok": result.get("ok"),
                "conflicts": [c.get("code") for c in result.get("conflicts", [])],
            },
            data["clientEmail"],
        )
        return Response(redact_sensitive_values(result))
