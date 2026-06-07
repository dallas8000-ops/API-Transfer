from __future__ import annotations

from datetime import date, datetime

from rest_framework.response import Response
from rest_framework.views import APIView

from core.rbac import IsAdmin, IsOperator, IsViewer
from core.redaction import redact_sensitive_values
from deployments.framework_detector import detect_framework
from deployments.pipeline import run_pipeline

from . import adapters, planner, terraform
from .audit import list_audit, record_audit, verify_chain
from .serializers import (
    ApplyRequestSerializer,
    DeploymentRequestSerializer,
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
        record_audit("discover", request.rbac_actor, {"provider": provider}, app_identifier)
        return Response(redact_sensitive_values(result))


class PlanView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        serializer = MigrationSpecSerializer(data=request.data.get("spec", {}))
        serializer.is_valid(raise_exception=True)
        spec = serializer.validated_data
        result = planner.generate_plan(_to_plain(spec))
        record_audit("plan", request.rbac_actor, {"planId": result["plan"]["planId"]}, spec["appName"])
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


class DeployView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = DeploymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req = serializer.normalized()
        result = run_pipeline(req)
        status = 200 if result["succeeded"] else 207
        record_audit("apply", request.rbac_actor, {"deploymentId": result["deploymentId"], "succeeded": result["succeeded"]}, req["appName"])
        return Response(redact_sensitive_values({"result": result}), status=status)


class AuditView(APIView):
    permission_classes = [IsViewer]

    def get(self, request):
        entries = list_audit()
        return Response({"entries": entries, "valid": verify_chain()})


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
