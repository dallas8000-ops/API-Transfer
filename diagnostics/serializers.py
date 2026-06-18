from __future__ import annotations

from rest_framework import serializers

from .engine import DiagnosisRequest


class SecretSerializer(serializers.Serializer):
    key = serializers.CharField(min_length=1)
    value = serializers.CharField(min_length=1)


class DiagnosisRequestSerializer(serializers.Serializer):
    appName = serializers.CharField(min_length=1)
    targetProvider = serializers.ChoiceField(
        choices=["render", "railway", "fly", "kong", "terraform", "supabase", "orena"]
    )
    files = serializers.ListField(child=serializers.CharField(allow_blank=True), default=list)
    packageJson = serializers.DictField(required=False, allow_null=True)
    environment = serializers.DictField(child=serializers.CharField(allow_blank=True), default=dict)
    secrets = SecretSerializer(many=True, default=list)
    domain = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    region = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    domains = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    enableStripe = serializers.BooleanField(default=False)
    enableMonitoring = serializers.BooleanField(default=False)
    enableBackups = serializers.BooleanField(default=False)
    targetEnvironment = serializers.ChoiceField(choices=["dev", "stage", "prod"], default="stage")
    requestedBy = serializers.CharField(min_length=1)

    def to_domain(self) -> DiagnosisRequest:
        data = self.validated_data
        domain = data.get("domain") or None
        region = data.get("region") or None
        domains = list(data.get("domains") or [])
        if domain and not domains:
            domains = [{"host": domain, "tlsRequired": True}]
        return DiagnosisRequest(
            app_name=data["appName"],
            target_provider=data["targetProvider"],
            files=list(data.get("files", [])),
            environment=dict(data.get("environment", {})),
            secrets=[dict(s) for s in data.get("secrets", [])],
            target_environment=data.get("targetEnvironment", "stage"),
            requested_by=data["requestedBy"],
            package_json=data.get("packageJson") or None,
            domain=domain,
            region=region,
            domains=domains,
            enable_stripe=data.get("enableStripe", False),
            enable_monitoring=data.get("enableMonitoring", False),
            enable_backups=data.get("enableBackups", False),
        )


class DiagnosisFixRequestSerializer(serializers.Serializer):
    class RailwayTransferSerializer(serializers.Serializer):
        mode = serializers.ChoiceField(choices=["queue", "demand"], default="queue")
        only = serializers.ListField(child=serializers.CharField(min_length=1), required=False, default=list)
        redeployExisting = serializers.BooleanField(default=False)
        verify = serializers.BooleanField(default=True)
        verifyTimeout = serializers.IntegerField(min_value=10, default=240)
        verifyInterval = serializers.IntegerField(min_value=3, default=10)
        serviceTimeout = serializers.IntegerField(min_value=30, default=180)
        allowOverlap = serializers.BooleanField(default=False)
        dryRun = serializers.BooleanField(default=False)

    project = DiagnosisRequestSerializer()
    issueIds = serializers.ListField(
        child=serializers.CharField(min_length=1), required=False, allow_null=True
    )
    railwayTransfer = RailwayTransferSerializer(required=False)
