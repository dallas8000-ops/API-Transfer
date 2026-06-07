from __future__ import annotations

import logging

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

        project = DiagnosisRequestSerializer(data=request.data["project"])
        project.is_valid(raise_exception=True)
        result = apply_fixes(project.to_domain(), issue_ids)

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
