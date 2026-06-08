from __future__ import annotations

from rest_framework import serializers


class IssueLicenseSerializer(serializers.Serializer):
    subscriptionId = serializers.CharField()
    registeredDomain = serializers.CharField()
    maxInstances = serializers.IntegerField(required=False, min_value=1, default=1)


class ValidateLicenseSerializer(serializers.Serializer):
    licenseKey = serializers.CharField()
    domain = serializers.CharField()
    instanceId = serializers.CharField()


class RevokeLicenseSerializer(serializers.Serializer):
    licenseKey = serializers.CharField()
