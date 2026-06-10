from __future__ import annotations

import json
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as dj_timezone

from migrationengine.models import TransferRun


class Command(BaseCommand):
    help = "Check transfer worker health and fail when queue alerts are active."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON payload.")
        parser.add_argument(
            "--no-fail-on-alert",
            action="store_false",
            dest="fail_on_alert",
            help="Return success status even if any alert is active.",
        )
        parser.set_defaults(fail_on_alert=True)
        parser.add_argument("--dead-letter-threshold", type=int, default=None)
        parser.add_argument("--retryable-threshold", type=int, default=None)
        parser.add_argument("--stale-lease-threshold", type=int, default=None)

    def handle(self, *args, **options):
        now = dj_timezone.now()
        payload = self._health_payload(
            now=now,
            dead_letter_threshold=options.get("dead_letter_threshold"),
            retryable_threshold=options.get("retryable_threshold"),
            stale_lease_threshold=options.get("stale_lease_threshold"),
        )

        if bool(options.get("json")):
            self.stdout.write(json.dumps(payload))
        else:
            self.stdout.write(self._text_payload(payload))

        has_active_alert = any(metric["active"] for metric in payload["alerts"].values())
        if has_active_alert and bool(options.get("fail_on_alert", True)):
            raise CommandError("Transfer worker health check failed: one or more alerts are active.")

    def _health_payload(
        self,
        now,
        dead_letter_threshold: int | None,
        retryable_threshold: int | None,
        stale_lease_threshold: int | None,
    ) -> dict:
        dead_letter_count = TransferRun.objects.filter(status=TransferRun.STATUS_DEAD_LETTER).count()
        retryable_count = TransferRun.objects.filter(status=TransferRun.STATUS_RETRYABLE).count()
        stale_lease_count = TransferRun.objects.filter(
            status=TransferRun.STATUS_RUNNING,
            lease_expires_at__isnull=False,
            lease_expires_at__lt=now,
        ).count()

        dead_threshold = self._threshold(
            dead_letter_threshold,
            int(getattr(settings, "TRANSFER_ALERT_DEAD_LETTER_THRESHOLD", 5)),
        )
        retry_threshold = self._threshold(
            retryable_threshold,
            int(getattr(settings, "TRANSFER_ALERT_RETRYABLE_THRESHOLD", 10)),
        )
        stale_threshold = self._threshold(
            stale_lease_threshold,
            int(getattr(settings, "TRANSFER_ALERT_STALE_LEASE_THRESHOLD", 1)),
        )

        return {
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "alerts": {
                "deadLetter": {
                    "active": dead_letter_count >= dead_threshold,
                    "count": dead_letter_count,
                    "threshold": dead_threshold,
                },
                "retryableBacklog": {
                    "active": retryable_count >= retry_threshold,
                    "count": retryable_count,
                    "threshold": retry_threshold,
                },
                "staleLeases": {
                    "active": stale_lease_count >= stale_threshold,
                    "count": stale_lease_count,
                    "threshold": stale_threshold,
                },
            },
        }

    def _text_payload(self, payload: dict) -> str:
        lines = [f"transfer-worker-health generatedAt={payload['generatedAt']}"]
        for key in ["deadLetter", "retryableBacklog", "staleLeases"]:
            metric = payload["alerts"][key]
            state = "active" if metric["active"] else "ok"
            lines.append(f"{key}={state} count={metric['count']} threshold={metric['threshold']}")
        return "\n".join(lines)

    def _threshold(self, raw_value: int | None, default_value: int) -> int:
        if raw_value is None:
            return max(0, default_value)
        return max(0, int(raw_value))