from __future__ import annotations

from datetime import date, datetime

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
from core.rbac import IsAdmin, IsOperator, IsViewer
from core.redaction import redact_sensitive_values
from deployments.framework_detector import detect_framework
from deployments.pipeline import run_pipeline

from . import adapters, planner, providers, terraform
from .audit import list_audit, record_audit, verify_chain
from .github_import import GitHubImportError, import_repository
from .models import DeploymentRun
from .serializers import (
    ApplyRequestSerializer,
    DeploymentRequestSerializer,
    GitHubImportSerializer,
    MigrationSpecSerializer,
)


class DiscoverView(APIView):
    permission_classes = [IsViewer]

    def post(self, request):
        provider = request.data.get("provider")
        app_identifier = request.data.get("appIdentifier")
        if not provider or not app_identifier:
            return Response({"error": "provider and appIdentifier are required."}, status=400)
        if provider not in adapters.SUPPORTED_PROVIDERS:
            return Response({"error": f"Unsupported provider '{provider}'."}, status=400)

        result = adapters.discover(provider, app_identifier)
        result["liveExecution"] = _provider_live_status(provider)
        record_audit("discover", request.rbac_actor, {"provider": provider}, app_identifier)
        return Response(redact_sensitive_values(result))


class PlanView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        ctx = get_or_create_workspace(account_email_from_request(request))
        limit_response = check_limit(ctx, "migration")
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
        live_capable = _provider_live_status(req["targetProvider"])["liveEnabled"]
        if live_capable:
            limit_response = check_limit(ctx, "live_deployment")
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
                "exportedAt": datetime.utcnow().isoformat() + "Z",
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
        for provider in ["github", "render", "railway", "fly", "kong", "terraform", "supabase", "cloudflare", "stripe"]:
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
        return Response({"providers": providers, "entitlements": entitlements_payload(ctx)})


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
        payload = {"status": "unknown", "message": f"Status polling is not implemented for {run.target_provider} yet."}
        run.mark_status("unknown", payload)
        return Response({"run": run.to_dict()})


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
            "liveEnabled": bool(settings.RENDER_API_TOKEN and settings.RENDER_OWNER_ID),
            "capabilities": ["deploy", "env-vars", "deploy-trigger"],
            "message": "Live Render deploys are enabled when RENDER_API_TOKEN and RENDER_OWNER_ID are configured.",
        },
        "railway": {
            "liveEnabled": False,
            "capabilities": ["canonical-discovery"],
            "message": "Railway is currently provider-neutral planning only.",
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
