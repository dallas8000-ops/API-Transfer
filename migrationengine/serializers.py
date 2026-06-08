from __future__ import annotations

from rest_framework import serializers

PROVIDERS = ["render", "railway", "fly", "kong", "terraform", "supabase"]


class SecretSerializer(serializers.Serializer):
    key = serializers.CharField(min_length=1)
    value = serializers.CharField(min_length=1)


class ServiceSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=1)
    runtime = serializers.ChoiceField(choices=["node", "python", "go", "docker", "static"])
    buildCommand = serializers.CharField(required=False, allow_blank=True)
    startCommand = serializers.CharField(required=False, allow_blank=True)
    region = serializers.CharField(required=False, allow_blank=True)
    replicas = serializers.IntegerField(required=False, min_value=1)
    environment = serializers.DictField(child=serializers.CharField(allow_blank=True), default=dict)
    secrets = SecretSerializer(many=True, default=list)


class DomainSerializer(serializers.Serializer):
    host = serializers.CharField(min_length=1)
    path = serializers.CharField(required=False, allow_blank=True)
    tlsRequired = serializers.BooleanField()


class DatabaseSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=1)
    engine = serializers.ChoiceField(choices=["postgres", "mysql", "redis"])
    version = serializers.CharField(required=False, allow_blank=True)


class MetadataSerializer(serializers.Serializer):
    requestedBy = serializers.CharField(min_length=1)
    requestedAt = serializers.DateTimeField()
    environment = serializers.ChoiceField(choices=["dev", "stage", "prod"])


class MigrationSpecSerializer(serializers.Serializer):
    appName = serializers.CharField(min_length=1)
    sourceProvider = serializers.ChoiceField(choices=PROVIDERS)
    targetProvider = serializers.ChoiceField(choices=PROVIDERS)
    services = ServiceSerializer(many=True)
    domains = DomainSerializer(many=True)
    databases = DatabaseSerializer(many=True)
    metadata = MetadataSerializer()


class ApplyRequestSerializer(serializers.Serializer):
    spec = MigrationSpecSerializer()
    # Plan passes through untouched: its SHA-256 integrityHash is re-verified on
    # apply, so type coercion here would falsely fail that check.
    plan = serializers.DictField()
    approvedBy = serializers.CharField(min_length=3)

    def validate_plan(self, value):
        required = {"planId", "integrityHash"}
        missing = required - set(value)
        if missing:
            raise serializers.ValidationError(f"Plan is missing fields: {', '.join(sorted(missing))}.")
        return value


class DeploymentRequestSerializer(serializers.Serializer):
    appName = serializers.CharField(min_length=1)
    targetProvider = serializers.ChoiceField(choices=PROVIDERS)
    region = serializers.CharField(required=False, allow_blank=True)
    files = serializers.ListField(child=serializers.CharField(allow_blank=True), default=list)
    packageJson = serializers.DictField(required=False, allow_null=True)
    repoUrl = serializers.URLField(required=False, allow_blank=True)
    branch = serializers.CharField(required=False, allow_blank=True)
    environment = serializers.DictField(child=serializers.CharField(allow_blank=True), default=dict)
    secrets = SecretSerializer(many=True, default=list)
    domain = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    enableStripe = serializers.BooleanField(default=False)
    enableMonitoring = serializers.BooleanField(default=False)
    enableBackups = serializers.BooleanField(default=False)
    requestedBy = serializers.CharField(min_length=1)
    targetEnvironment = serializers.ChoiceField(choices=["dev", "stage", "prod"], default="stage")

    def normalized(self) -> dict:
        data = dict(self.validated_data)
        data["domain"] = data.get("domain") or None
        data["packageJson"] = data.get("packageJson") or None
        data["repoUrl"] = data.get("repoUrl") or ""
        data["branch"] = data.get("branch") or ""
        data["secrets"] = [dict(s) for s in data.get("secrets", [])]
        data["environment"] = dict(data.get("environment", {}))
        data["files"] = list(data.get("files", []))
        return data


class GitHubImportSerializer(serializers.Serializer):
    repoUrl = serializers.CharField(min_length=1)
    branch = serializers.CharField(required=False, allow_blank=True)
    accessToken = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
