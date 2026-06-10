from __future__ import annotations

import os
import random
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone as dj_timezone

from migrationengine.models import TransferRun


class Command(BaseCommand):
    help = "Process queued TransferRun jobs with retry/backoff and checkpoint updates."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
        parser.add_argument(
            "--limit",
            type=int,
            default=int(getattr(settings, "TRANSFER_WORKER_LIMIT", 5)),
            help="Max runs to claim per batch.",
        )
        parser.add_argument(
            "--poll-interval",
            type=int,
            default=int(getattr(settings, "TRANSFER_WORKER_POLL_INTERVAL_SECONDS", 5)),
            help="Seconds to sleep when no work is found.",
        )
        parser.add_argument(
            "--lease-ttl",
            type=int,
            default=int(getattr(settings, "TRANSFER_WORKER_LEASE_TTL_SECONDS", 120)),
            help="Lease TTL in seconds for claimed runs.",
        )
        parser.add_argument(
            "--heartbeat-interval",
            type=int,
            default=int(getattr(settings, "TRANSFER_WORKER_HEARTBEAT_INTERVAL_SECONDS", 15)),
            help="Heartbeat interval in seconds while executing.",
        )
        parser.add_argument(
            "--workspace-concurrency-cap",
            type=int,
            default=int(getattr(settings, "TRANSFER_WORKSPACE_CONCURRENCY_CAP", 1)),
            help="Maximum number of concurrent running transfer jobs per workspace.",
        )
        parser.add_argument(
            "--aging-window",
            type=int,
            default=int(getattr(settings, "TRANSFER_QUEUE_AGING_WINDOW_SECONDS", 300)),
            help="Seconds per aging step added to queue priority.",
        )
        parser.add_argument(
            "--max-aging-boost",
            type=int,
            default=int(getattr(settings, "TRANSFER_QUEUE_MAX_AGING_BOOST", 10)),
            help="Maximum priority points added via queue aging.",
        )
        parser.add_argument("--worker-id", default="", help="Optional worker identifier for logs and step details.")

    def handle(self, *args, **options):
        once = bool(options["once"])
        limit = max(1, int(options["limit"]))
        poll_interval = max(1, int(options["poll_interval"]))
        lease_ttl = max(30, int(options["lease_ttl"]))
        heartbeat_interval = max(3, int(options["heartbeat_interval"]))
        workspace_concurrency_cap = max(1, int(options["workspace_concurrency_cap"]))
        aging_window = max(1, int(options["aging_window"]))
        max_aging_boost = max(0, int(options["max_aging_boost"]))
        worker_id = str(options.get("worker_id") or f"worker-{uuid.uuid4().hex[:8]}")

        self.stdout.write(self.style.NOTICE(f"Transfer worker started as {worker_id}"))

        while True:
            processed = self._process_batch(
                limit=limit,
                worker_id=worker_id,
                lease_ttl=lease_ttl,
                heartbeat_interval=heartbeat_interval,
                workspace_concurrency_cap=workspace_concurrency_cap,
                aging_window=aging_window,
                max_aging_boost=max_aging_boost,
            )
            if once:
                break
            if processed == 0:
                time.sleep(poll_interval)

        self.stdout.write(self.style.SUCCESS("Transfer worker finished."))

    def _process_batch(
        self,
        limit: int,
        worker_id: str,
        lease_ttl: int = 120,
        heartbeat_interval: int = 15,
        workspace_concurrency_cap: int = 1,
        aging_window: int = 300,
        max_aging_boost: int = 10,
    ) -> int:
        self._recover_stale_claims()
        now = dj_timezone.now()
        queryset = (
            TransferRun.objects.filter(status__in=[TransferRun.STATUS_QUEUED, TransferRun.STATUS_RETRYABLE, TransferRun.STATUS_PENDING])
            .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
            .filter(Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
            .order_by("created_at")
        )

        running_counts = self._running_counts_by_workspace(now)
        candidates = list(queryset[: max(limit * 10, limit)])
        candidates = self._prioritized_candidates(
            candidates,
            now=now,
            aging_window=aging_window,
            max_aging_boost=max_aging_boost,
        )
        processed = 0
        for run in candidates:
            workspace_key = self._workspace_key(run)
            cap = self._workspace_cap_for_run(run, workspace_concurrency_cap)
            if running_counts.get(workspace_key, 0) >= cap:
                continue
            if not self._claim_run(run.id, worker_id=worker_id, lease_ttl=lease_ttl):
                continue
            processed += 1
            running_counts[workspace_key] = running_counts.get(workspace_key, 0) + 1
            self._execute_run(run.id, worker_id, lease_ttl, heartbeat_interval)
            if processed >= limit:
                break
        return processed

    def _running_counts_by_workspace(self, now) -> dict[int, int]:
        counts: dict[int, int] = {}
        rows = TransferRun.objects.filter(
            status=TransferRun.STATUS_RUNNING,
            lease_expires_at__isnull=False,
            lease_expires_at__gt=now,
        ).values_list("workspace_id")
        for (workspace_id,) in rows:
            key = int(workspace_id or 0)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _workspace_key(self, run: TransferRun) -> int:
        return int(run.workspace_id or 0)

    def _workspace_cap_for_run(self, run: TransferRun, default_cap: int) -> int:
        options = run.options or {}
        override = options.get("workspaceConcurrencyCap")
        if isinstance(override, int) and override > 0:
            return override
        return default_cap

    def _prioritized_candidates(
        self,
        runs: list[TransferRun],
        now,
        aging_window: int,
        max_aging_boost: int,
    ) -> list[TransferRun]:
        return sorted(
            runs,
            key=lambda run: (
                -self._effective_priority(run, now=now, aging_window=aging_window, max_aging_boost=max_aging_boost),
                run.created_at,
                run.id,
            ),
        )

    def _effective_priority(self, run: TransferRun, now, aging_window: int, max_aging_boost: int) -> int:
        base_priority = self._base_priority(run)
        age_seconds = max(0, int((now - run.created_at).total_seconds()))
        age_boost = min(max_aging_boost, age_seconds // max(1, aging_window))
        return base_priority + age_boost

    def _base_priority(self, run: TransferRun) -> int:
        options = run.options or {}
        value = options.get("queuePriority")
        if isinstance(value, int):
            return value
        return 0

    def _claim_run(self, run_pk: int, worker_id: str, lease_ttl: int) -> bool:
        now = dj_timezone.now()
        updated = (
            TransferRun.objects.filter(id=run_pk, status__in=[TransferRun.STATUS_QUEUED, TransferRun.STATUS_RETRYABLE, TransferRun.STATUS_PENDING])
            .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
            .filter(Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
            .update(
                status=TransferRun.STATUS_RUNNING,
                step=TransferRun.STEP_STARTING,
                attempt_started_at=now,
                next_retry_at=None,
                last_error="",
                lease_owner=worker_id,
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=max(1, lease_ttl)),
            )
        )
        return bool(updated)

    def _execute_run(self, run_pk: int, worker_id: str, lease_ttl: int, heartbeat_interval: int) -> None:
        run = TransferRun.objects.get(id=run_pk)
        if not self._owns_lease(run_pk, worker_id):
            return
        if self._can_resume_from_transfer_checkpoint(run):
            run.mark_step(
                TransferRun.STEP_VERIFY,
                details={"workerId": worker_id, "replayedFrom": TransferRun.STEP_TRANSFER, "checkpoint": True},
            )
            self._finalize_success(run_pk, worker_id)
            return

        run.mark_step(
            TransferRun.STEP_STARTING,
            status=TransferRun.STATUS_RUNNING,
            details={"workerId": worker_id, "attempt": run.retry_count + 1},
        )
        if not self._heartbeat_lease(run_pk, worker_id, lease_ttl):
            return

        timeout_seconds = int((run.options or {}).get("workerTimeout") or 3600)
        log_path = run.log_path or os.path.join(str(settings.BASE_DIR), "data", f"transfer-{run.run_id}.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        run.log_path = log_path
        run.step = TransferRun.STEP_TRANSFER
        run.save(update_fields=["log_path", "step", "updated_at"])
        run.mark_step(
            TransferRun.STEP_TRANSFER,
            details={"workerId": worker_id, "attempt": run.retry_count + 1, "startedAt": dj_timezone.now().isoformat()},
        )

        try:
            return_code = self._run_command_with_heartbeat(
                run_pk=run_pk,
                command=run.command,
                worker_id=worker_id,
                lease_ttl=lease_ttl,
                heartbeat_interval=heartbeat_interval,
                timeout_seconds=timeout_seconds,
                log_path=log_path,
                run_id=run.run_id,
            )

            if return_code == 0:
                run.refresh_from_db()
                if not self._owns_lease(run_pk, worker_id):
                    return
                run.mark_step(
                    TransferRun.STEP_TRANSFER,
                    details={
                        "workerId": worker_id,
                        "completedAt": dj_timezone.now().isoformat(),
                        "completed": True,
                        "exitCode": 0,
                    },
                )
                run.mark_step(TransferRun.STEP_VERIFY, details={"exitCode": 0})
                self._finalize_success(run_pk, worker_id)
                return

            error = f"Transfer command exited with code {return_code}"
            run.mark_step(
                TransferRun.STEP_TRANSFER,
                details={
                    "workerId": worker_id,
                    "completedAt": dj_timezone.now().isoformat(),
                    "completed": False,
                    "exitCode": return_code,
                },
            )
            self._retry_run(
                run,
                error,
                return_code,
                retryable=self._is_retryable_error(error, return_code),
                worker_id=worker_id,
            )
        except subprocess.TimeoutExpired:
            error = f"Transfer command timed out after {timeout_seconds}s"
            self._retry_run(run, error, None, retryable=True, worker_id=worker_id)
        except Exception as exc:  # noqa: BLE001
            error = f"Worker execution error: {exc}"
            self._retry_run(
                run,
                error,
                None,
                retryable=self._is_retryable_error(error, None),
                worker_id=worker_id,
            )

    def _retry_run(
        self,
        run: TransferRun,
        error: str,
        exit_code: int | None,
        retryable: bool,
        worker_id: str,
    ) -> None:
        run.refresh_from_db()
        if run.lease_owner and run.lease_owner != worker_id:
            return

        run.step = TransferRun.STEP_FINALIZE
        run.exit_code = exit_code
        run.save(update_fields=["step", "exit_code", "updated_at"])

        if retryable:
            delay = self._compute_retry_delay(run.retry_count)
            run.schedule_retry(error=error, delay_seconds=delay)
            if run.status == TransferRun.STATUS_FAILED:
                run.status = TransferRun.STATUS_DEAD_LETTER
                run.finished_at = dj_timezone.now()
                run.save(update_fields=["status", "finished_at", "updated_at"])
            return

        run.status = TransferRun.STATUS_DEAD_LETTER
        run.last_error = error
        run.finished_at = dj_timezone.now()
        run.next_retry_at = None
        run.lease_owner = ""
        run.lease_expires_at = None
        run.heartbeat_at = None
        run.save(
            update_fields=[
                "status",
                "last_error",
                "finished_at",
                "next_retry_at",
                "lease_owner",
                "lease_expires_at",
                "heartbeat_at",
                "updated_at",
            ]
        )

    def _finalize_success(self, run_pk: int, worker_id: str) -> None:
        run = TransferRun.objects.filter(id=run_pk, lease_owner=worker_id).first()
        if run is None:
            return
        run.status = TransferRun.STATUS_SUCCEEDED
        run.step = TransferRun.STEP_FINALIZE
        run.exit_code = 0
        run.finished_at = dj_timezone.now()
        run.next_retry_at = None
        run.last_error = ""
        run.lease_owner = ""
        run.lease_expires_at = None
        run.heartbeat_at = None
        run.save(
            update_fields=[
                "status",
                "step",
                "exit_code",
                "finished_at",
                "next_retry_at",
                "last_error",
                "lease_owner",
                "lease_expires_at",
                "heartbeat_at",
                "updated_at",
            ]
        )

    def _can_resume_from_transfer_checkpoint(self, run: TransferRun) -> bool:
        options = run.options or {}
        if options.get("replayFromCheckpoint", True) is False:
            return False
        step_state = run.step_state or {}
        transfer_checkpoint = step_state.get(TransferRun.STEP_TRANSFER) or {}
        details = transfer_checkpoint.get("details") or {}
        return bool(details.get("completed") and details.get("exitCode") == 0)

    def _recover_stale_claims(self) -> None:
        now = dj_timezone.now()
        stale_runs = TransferRun.objects.filter(
            status=TransferRun.STATUS_RUNNING,
            lease_expires_at__isnull=False,
            lease_expires_at__lt=now,
        )
        for run in stale_runs:
            run.step = TransferRun.STEP_FINALIZE
            run.exit_code = None
            run.save(update_fields=["step", "exit_code", "updated_at"])
            run.schedule_retry(error="Worker lease expired before completion.", delay_seconds=30)

    def _run_command_with_heartbeat(
        self,
        run_pk: int,
        command: list[str],
        worker_id: str,
        lease_ttl: int,
        heartbeat_interval: int,
        timeout_seconds: int,
        log_path: str,
        run_id: str,
    ) -> int:
        start = dj_timezone.now()
        deadline = start + timedelta(seconds=max(30, timeout_seconds))

        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"\n[{datetime.now(timezone.utc).isoformat()}] Worker {worker_id} starting run {run_id}\n")
            process = subprocess.Popen(  # noqa: S603
                command,
                cwd=str(settings.BASE_DIR),
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
            while True:
                try:
                    return process.wait(timeout=max(1, heartbeat_interval))
                except subprocess.TimeoutExpired:
                    if dj_timezone.now() >= deadline:
                        process.kill()
                        process.wait(timeout=5)
                        raise subprocess.TimeoutExpired(command, timeout_seconds)
                    if not self._heartbeat_lease(run_pk, worker_id, lease_ttl):
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        raise RuntimeError("Worker lease ownership lost during execution.")

    def _owns_lease(self, run_pk: int, worker_id: str) -> bool:
        now = dj_timezone.now()
        return TransferRun.objects.filter(
            id=run_pk,
            lease_owner=worker_id,
            status=TransferRun.STATUS_RUNNING,
            lease_expires_at__isnull=False,
            lease_expires_at__gt=now,
        ).exists()

    def _heartbeat_lease(self, run_pk: int, worker_id: str, lease_ttl: int) -> bool:
        now = dj_timezone.now()
        updated = TransferRun.objects.filter(
            id=run_pk,
            lease_owner=worker_id,
            status=TransferRun.STATUS_RUNNING,
        ).update(
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=max(1, lease_ttl)),
        )
        return bool(updated)

    def _compute_retry_delay(self, retry_count: int) -> int:
        base = min(900, (2 ** max(0, retry_count)) * 30)
        jitter = random.randint(0, min(15, base // 4))
        return base + jitter

    def _is_retryable_error(self, error: str, exit_code: int | None) -> bool:
        text = (error or "").lower()
        terminal_tokens = [
            "unauthorized",
            "forbidden",
            "authentication",
            "invalid token",
            "missing required configuration",
            "usage",
            "argument",
        ]
        if any(token in text for token in terminal_tokens):
            return False
        if exit_code in {2, 64}:
            return False
        return True
