from __future__ import annotations

import logging
import shlex

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.rbac import IsOperator, IsViewer
from core.redaction import redact_sensitive_values
from migrationengine.audit import record_audit

from .engine import apply_fixes, analyze_project
from .serializers import DiagnosisFixRequestSerializer, DiagnosisRequestSerializer

logger = logging.getLogger("diagnostics")


class DiagnoseView(APIView):
    permission_classes = [IsViewer]

    def post(self, request: Request) -> Response:
        serializer = DiagnosisRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = analyze_project(serializer.to_domain())

        record_audit(
            "discover",
            getattr(request, "rbac_actor", "unknown"),
            {"kind": "diagnose", "issues": report["summary"]["total"], "healthScore": report["summary"]["healthScore"]},
            report["diagnosisId"],
        )
        logger.info(
            "Project diagnosis completed id=%s issues=%s health=%s",
            report["diagnosisId"],
            report["summary"]["total"],
            report["summary"]["healthScore"],
        )
        return Response({"report": redact_sensitive_values(report)})


class DiagnoseFixView(APIView):
    permission_classes = [IsOperator]

    def post(self, request: Request) -> Response:
        serializer = DiagnosisFixRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issue_ids = serializer.validated_data.get("issueIds")
        transfer = serializer.validated_data.get("railwayTransfer")

        project = DiagnosisRequestSerializer(data=request.data["project"])
        project.is_valid(raise_exception=True)
        result = apply_fixes(project.to_domain(), issue_ids)
        result["railwayTransferActions"] = _railway_transfer_actions(project.validated_data, transfer)

        record_audit(
            "apply",
            getattr(request, "rbac_actor", "unknown"),
            {"kind": "diagnose-fix", "applied": len(result["applied"]), "residual": result["residualReport"]["summary"]["total"]},
            result["diagnosisId"],
        )
        logger.info(
            "Project auto-fix applied id=%s applied=%s residual=%s",
            result["diagnosisId"],
            len(result["applied"]),
            result["residualReport"]["summary"]["total"],
        )
        return Response({"result": redact_sensitive_values(result)}, status=status.HTTP_200_OK)


def _railway_transfer_actions(project: dict, transfer: dict | None) -> dict:
    target_provider = str(project.get("targetProvider") or "").lower()
    app_name = str(project.get("appName") or "").strip()

    defaults = {
        "mode": "queue",
        "only": [app_name] if app_name else [],
        "redeployExisting": False,
        "verify": True,
        "verifyTimeout": 240,
        "verifyInterval": 10,
        "serviceTimeout": 180,
        "allowOverlap": False,
        "dryRun": False,
    }
    cfg = {**defaults, **(transfer or {})}

    base = "python manage.py transfer_render_to_railway"
    common_flags: list[str] = []
    if cfg["redeployExisting"]:
        common_flags.append("--redeploy-existing")
    if not cfg["verify"]:
        common_flags.append("--no-verify")
    common_flags.extend(
        [
            f"--verify-timeout {int(cfg['verifyTimeout'])}",
            f"--verify-interval {int(cfg['verifyInterval'])}",
            f"--service-timeout {int(cfg['serviceTimeout'])}",
        ]
    )
    if cfg["allowOverlap"]:
        common_flags.append("--allow-overlap")
    if cfg["dryRun"]:
        common_flags.append("--dry-run")

    queue_cmd = " ".join([base, "--mode queue", *common_flags]).strip()

    demand_parts = [base, "--mode demand"]
    only_values = [str(v).strip() for v in cfg.get("only", []) if str(v).strip()]
    for value in only_values:
        demand_parts.append(f"--only {shlex.quote(value)}")
    demand_parts.extend(common_flags)
    demand_cmd = " ".join(demand_parts).strip()

    return {
        "enabled": target_provider in {"railway", "render"},
        "recommendedMode": cfg["mode"],
        "notes": [
            "Queue mode runs serialized one-at-a-time.",
            "Demand mode targets specific service names or Render ids via --only.",
        ],
        "commands": {
            "queue": queue_cmd,
            "demand": demand_cmd,
        },
    }
