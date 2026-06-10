from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from billing.models import Workspace
from migrationengine.management.commands.transfer_worker import Command
from migrationengine.models import TransferRun


class TransferWorkerTests(TestCase):
    def setUp(self):
        self.command = Command()

    @override_settings(
        TRANSFER_WORKER_LIMIT=9,
        TRANSFER_WORKER_POLL_INTERVAL_SECONDS=11,
        TRANSFER_WORKER_LEASE_TTL_SECONDS=150,
        TRANSFER_WORKER_HEARTBEAT_INTERVAL_SECONDS=17,
        TRANSFER_WORKSPACE_CONCURRENCY_CAP=3,
        TRANSFER_QUEUE_AGING_WINDOW_SECONDS=200,
        TRANSFER_QUEUE_MAX_AGING_BOOST=8,
    )
    def test_worker_argument_defaults_use_settings(self):
        parser = self.command.create_parser("manage.py", "transfer_worker")
        options = parser.parse_args([])

        self.assertEqual(options.limit, 9)
        self.assertEqual(options.poll_interval, 11)
        self.assertEqual(options.lease_ttl, 150)
        self.assertEqual(options.heartbeat_interval, 17)
        self.assertEqual(options.workspace_concurrency_cap, 3)
        self.assertEqual(options.aging_window, 200)
        self.assertEqual(options.max_aging_boost, 8)

    @patch.object(Command, "_run_command_with_heartbeat")
    def test_worker_succeeds_queued_run(self, run_with_heartbeat):
        run_with_heartbeat.return_value = 0
        run = TransferRun.objects.create(
            run_id="worker-ok",
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={},
            log_path="",
        )

        processed = self.command._process_batch(limit=5, worker_id="test-worker")
        run.refresh_from_db()

        self.assertEqual(processed, 1)
        self.assertEqual(run.status, TransferRun.STATUS_SUCCEEDED)
        self.assertEqual(run.step, TransferRun.STEP_FINALIZE)
        self.assertEqual(run.exit_code, 0)
        self.assertEqual(run.lease_owner, "")
        self.assertIsNone(run.lease_expires_at)
        self.assertIsNone(run.heartbeat_at)

    @patch.object(Command, "_run_command_with_heartbeat")
    def test_worker_marks_retryable_on_failure(self, run_with_heartbeat):
        run_with_heartbeat.return_value = 1
        run = TransferRun.objects.create(
            run_id="worker-fail",
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={},
            log_path="",
            max_retries=3,
        )

        processed = self.command._process_batch(limit=5, worker_id="test-worker")
        run.refresh_from_db()

        self.assertEqual(processed, 1)
        self.assertEqual(run.status, TransferRun.STATUS_RETRYABLE)
        self.assertEqual(run.step, TransferRun.STEP_FINALIZE)
        self.assertEqual(run.retry_count, 1)
        self.assertIsNotNone(run.next_retry_at)

    def test_worker_recovers_stale_running_claim(self):
        run = TransferRun.objects.create(
            run_id="worker-stale",
            status=TransferRun.STATUS_RUNNING,
            step=TransferRun.STEP_TRANSFER,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={},
            log_path="",
            lease_owner="dead-worker",
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )

        self.command._recover_stale_claims()
        run.refresh_from_db()

        self.assertEqual(run.status, TransferRun.STATUS_RETRYABLE)
        self.assertEqual(run.retry_count, 1)
        self.assertEqual(run.lease_owner, "")
        self.assertIsNotNone(run.next_retry_at)

    @patch.object(Command, "_run_command_with_heartbeat")
    def test_worker_replays_from_transfer_checkpoint(self, run_with_heartbeat):
        run_with_heartbeat.return_value = 0
        run = TransferRun.objects.create(
            run_id="worker-replay",
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={"replayFromCheckpoint": True},
            step_state={
                TransferRun.STEP_TRANSFER: {
                    "updatedAt": timezone.now().isoformat(),
                    "details": {"completed": True, "exitCode": 0},
                }
            },
            log_path="",
        )

        processed = self.command._process_batch(limit=5, worker_id="test-worker")
        run.refresh_from_db()

        self.assertEqual(processed, 1)
        self.assertEqual(run.status, TransferRun.STATUS_SUCCEEDED)
        self.assertEqual(run.step, TransferRun.STEP_FINALIZE)
        self.assertEqual(run.exit_code, 0)
        run_with_heartbeat.assert_not_called()

    @patch.object(Command, "_run_command_with_heartbeat")
    def test_worker_marks_terminal_failure_without_retry(self, run_with_heartbeat):
        run_with_heartbeat.return_value = 2
        run = TransferRun.objects.create(
            run_id="worker-terminal",
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={},
            log_path="",
            max_retries=3,
        )

        processed = self.command._process_batch(limit=5, worker_id="test-worker")
        run.refresh_from_db()

        self.assertEqual(processed, 1)
        self.assertEqual(run.status, TransferRun.STATUS_DEAD_LETTER)
        self.assertEqual(run.retry_count, 0)
        self.assertIsNone(run.next_retry_at)
        self.assertEqual(run.lease_owner, "")
        self.assertIn("code 2", run.last_error)

    @patch.object(Command, "_run_command_with_heartbeat")
    def test_worker_enforces_workspace_concurrency_cap(self, run_with_heartbeat):
        run_with_heartbeat.return_value = 0
        workspace_a = Workspace.objects.create(name="A", owner_email="a@example.com")
        workspace_b = Workspace.objects.create(name="B", owner_email="b@example.com")

        TransferRun.objects.create(
            run_id="active-a",
            workspace=workspace_a,
            status=TransferRun.STATUS_RUNNING,
            step=TransferRun.STEP_TRANSFER,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={},
            lease_owner="worker-active",
            lease_expires_at=timezone.now() + timedelta(seconds=120),
            heartbeat_at=timezone.now(),
            log_path="",
        )
        blocked = TransferRun.objects.create(
            run_id="queued-a",
            workspace=workspace_a,
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={},
            log_path="",
        )
        allowed = TransferRun.objects.create(
            run_id="queued-b",
            workspace=workspace_b,
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={},
            log_path="",
        )

        processed = self.command._process_batch(limit=2, worker_id="test-worker", workspace_concurrency_cap=1)
        blocked.refresh_from_db()
        allowed.refresh_from_db()

        self.assertEqual(processed, 1)
        self.assertEqual(blocked.status, TransferRun.STATUS_QUEUED)
        self.assertEqual(allowed.status, TransferRun.STATUS_SUCCEEDED)

    @patch.object(Command, "_run_command_with_heartbeat")
    def test_worker_prefers_higher_queue_priority(self, run_with_heartbeat):
        run_with_heartbeat.return_value = 0

        low = TransferRun.objects.create(
            run_id="prio-low",
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={"queuePriority": 1},
            log_path="",
        )
        high = TransferRun.objects.create(
            run_id="prio-high",
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={"queuePriority": 5},
            log_path="",
        )

        processed = self.command._process_batch(limit=1, worker_id="test-worker")
        low.refresh_from_db()
        high.refresh_from_db()

        self.assertEqual(processed, 1)
        self.assertEqual(high.status, TransferRun.STATUS_SUCCEEDED)
        self.assertEqual(low.status, TransferRun.STATUS_QUEUED)

    @patch.object(Command, "_run_command_with_heartbeat")
    def test_worker_aging_promotes_older_jobs(self, run_with_heartbeat):
        run_with_heartbeat.return_value = 0

        older = TransferRun.objects.create(
            run_id="age-old",
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={"queuePriority": 0},
            log_path="",
        )
        newer = TransferRun.objects.create(
            run_id="age-new",
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={"queuePriority": 0},
            log_path="",
        )
        TransferRun.objects.filter(id=older.id).update(created_at=timezone.now() - timedelta(hours=2))

        processed = self.command._process_batch(
            limit=1,
            worker_id="test-worker",
            aging_window=60,
            max_aging_boost=10,
        )
        older.refresh_from_db()
        newer.refresh_from_db()

        self.assertEqual(processed, 1)
        self.assertEqual(older.status, TransferRun.STATUS_SUCCEEDED)
        self.assertEqual(newer.status, TransferRun.STATUS_QUEUED)
