from __future__ import annotations

from rest_framework import serializers

from .engine import DiagnosisRequest


class SecretSerializer(serializers.Serializer):
    key = serializers.CharField(min_length=1)
    value = serializers.CharField(min_length=1)


class DiagnosisRequestSerializer(serializers.Serializer):
    appName = serializers.CharField(min_length=1)
    targetProvider = serializers.ChoiceField(
        choices=["render", "railway", "fly", "kong", "terraform", "supabase"]
    )
    files = serializers.ListField(child=serializers.CharField(allow_blank=True), default=list)
    packageJson = serializers.DictField(required=False, allow_null=True)
    environment = serializers.DictField(child=serializers.CharField(allow_blank=True), default=dict)
    secrets = SecretSerializer(many=True, default=list)
    domain = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    enableStripe = serializers.BooleanField(default=False)
    enableMonitoring = serializers.BooleanField(default=False)
    enableBackups = serializers.BooleanField(default=False)
    targetEnvironment = serializers.ChoiceField(choices=["dev", "stage", "prod"], default="stage")
    requestedBy = serializers.CharField(min_length=1)

    def to_domain(self) -> DiagnosisRequest:
        data = self.validated_data
        domain = data.get("domain") or None
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
            enable_stripe=data.get("enableStripe", False),
            enable_monitoring=data.get("enableMonitoring", False),
            enable_backups=data.get("enableBackups", False),
        )


class DiagnosisFixRequestSerializer(serializers.Serializer):
    project = DiagnosisRequestSerializer()
    issueIds = serializers.ListField(
        child=serializers.CharField(min_length=1), required=False, allow_null=True
    )
