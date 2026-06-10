from __future__ import annotations

import json
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from migrationengine.models import TransferRun


class TransferWorkerHealthCommandTests(TestCase):
    @override_settings(
        TRANSFER_ALERT_DEAD_LETTER_THRESHOLD=3,
        TRANSFER_ALERT_RETRYABLE_THRESHOLD=3,
        TRANSFER_ALERT_STALE_LEASE_THRESHOLD=2,
    )
    def test_health_json_ok_when_under_thresholds(self):
        TransferRun.objects.create(
            run_id="health-ok-retryable",
            status=TransferRun.STATUS_RETRYABLE,
            command=["python", "manage.py"],
        )

        output = StringIO()
        call_command("transfer_worker_health", json=True, stdout=output)

        payload = json.loads(output.getvalue())
        self.assertFalse(payload["alerts"]["deadLetter"]["active"])
        self.assertFalse(payload["alerts"]["retryableBacklog"]["active"])
        self.assertFalse(payload["alerts"]["staleLeases"]["active"])

    @override_settings(
        TRANSFER_ALERT_DEAD_LETTER_THRESHOLD=1,
        TRANSFER_ALERT_RETRYABLE_THRESHOLD=10,
        TRANSFER_ALERT_STALE_LEASE_THRESHOLD=10,
    )
    def test_health_fails_when_alert_active(self):
        TransferRun.objects.create(
            run_id="health-dead-letter",
            status=TransferRun.STATUS_DEAD_LETTER,
            command=["python", "manage.py"],
        )

        with self.assertRaises(CommandError):
            call_command("transfer_worker_health", json=True, stdout=StringIO())

    @override_settings(
        TRANSFER_ALERT_DEAD_LETTER_THRESHOLD=5,
        TRANSFER_ALERT_RETRYABLE_THRESHOLD=5,
        TRANSFER_ALERT_STALE_LEASE_THRESHOLD=1,
    )
    def test_health_no_fail_mode_succeeds_with_active_alert(self):
        TransferRun.objects.create(
            run_id="health-stale",
            status=TransferRun.STATUS_RUNNING,
            command=["python", "manage.py"],
            lease_owner="worker-missing",
            lease_expires_at=timezone.now() - timezone.timedelta(minutes=1),
            heartbeat_at=timezone.now() - timezone.timedelta(minutes=2),
        )

        output = StringIO()
        call_command("transfer_worker_health", json=True, fail_on_alert=False, stdout=output)

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["alerts"]["staleLeases"]["active"])