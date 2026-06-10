from __future__ import annotations

from rest_framework.test import APIClient
from django.test import TestCase, override_settings
from django.utils import timezone

from billing.models import Workspace
from migrationengine.models import TransferRun
from migrationengine.views import _TRANSFER_STATE, _build_transfer_command, _transfer_status_payload


@override_settings(RBAC_VIEWER_KEYS=["viewer-test-key"], RBAC_OPERATOR_KEYS=[], RBAC_ADMIN_KEYS=[])
class TransferControlTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_build_transfer_command_queue_defaults(self):
        cmd = _build_transfer_command({"mode": "queue"})

        self.assertIn("manage.py", cmd)
        self.assertIn("transfer_render_to_railway", cmd)
        self.assertIn("--mode", cmd)
        self.assertIn("queue", cmd)

    def test_build_transfer_command_demand_options(self):
        cmd = _build_transfer_command(
            {
                "mode": "demand",
                "only": ["specwright-api", "BLOG-2"],
                "limit": 1,
                "redeployExisting": True,
                "verify": False,
                "verifyTimeout": 90,
                "verifyInterval": 5,
                "serviceTimeout": 60,
                "allowOverlap": True,
                "dryRun": True,
            }
        )

        joined = " ".join(cmd)
        self.assertIn("--mode demand", joined)
        self.assertIn("--only specwright-api", joined)
        self.assertIn("--only BLOG-2", joined)
        self.assertIn("--limit 1", joined)
        self.assertIn("--redeploy-existing", joined)
        self.assertIn("--no-verify", joined)
        self.assertIn("--verify-timeout 90", joined)
        self.assertIn("--verify-interval 5", joined)
        self.assertIn("--service-timeout 60", joined)
        self.assertIn("--allow-overlap", joined)
        self.assertIn("--dry-run", joined)

    def test_transfer_status_payload_without_run(self):
        payload = _transfer_status_payload()

        self.assertIn("running", payload)
        self.assertFalse(payload["running"])

    def test_transfer_history_returns_latest_runs(self):
        TransferRun.objects.create(run_id="run-1", status="failed", command=["python", "manage.py"])
        TransferRun.objects.create(run_id="run-2", status="succeeded", command=["python", "manage.py"])

        response = self.client.get("/api/migrations/transfer/history?limit=1", HTTP_X_API_KEY="viewer-test-key")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["runs"]), 1)
        self.assertEqual(body["runs"][0]["id"], "run-2")
        self.assertEqual(body["nextCursor"], str(TransferRun.objects.get(run_id="run-2").id))

    def test_transfer_history_cursor_paginates(self):
        first = TransferRun.objects.create(run_id="run-1", status="failed", command=["python", "manage.py"])
        second = TransferRun.objects.create(run_id="run-2", status="succeeded", command=["python", "manage.py"])
        TransferRun.objects.create(run_id="run-3", status="failed", command=["python", "manage.py"])

        page1 = self.client.get("/api/migrations/transfer/history?limit=2", HTTP_X_API_KEY="viewer-test-key")
        self.assertEqual(page1.status_code, 200)
        page1_body = page1.json()
        self.assertEqual([r["id"] for r in page1_body["runs"]], ["run-3", "run-2"])
        self.assertEqual(page1_body["nextCursor"], str(second.id))

        page2 = self.client.get(
            f"/api/migrations/transfer/history?limit=2&cursor={second.id}", HTTP_X_API_KEY="viewer-test-key"
        )
        self.assertEqual(page2.status_code, 200)
        page2_body = page2.json()
        self.assertEqual([r["id"] for r in page2_body["runs"]], ["run-1"])
        self.assertIsNone(page2_body["nextCursor"])

        self.assertTrue(first.id < second.id)

    def test_transfer_history_rejects_invalid_limit(self):
        response = self.client.get("/api/migrations/transfer/history?limit=abc", HTTP_X_API_KEY="viewer-test-key")

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_transfer_history_rejects_invalid_cursor(self):
        response = self.client.get("/api/migrations/transfer/history?cursor=bad", HTTP_X_API_KEY="viewer-test-key")

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    @override_settings(RBAC_OPERATOR_KEYS=["operator-test-key"])
    def test_transfer_replay_queues_dead_letter_run(self):
        run = TransferRun.objects.create(
            run_id="run-dead-letter",
            status=TransferRun.STATUS_DEAD_LETTER,
            step=TransferRun.STEP_FINALIZE,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={"mode": "queue"},
            retry_count=3,
            max_retries=3,
            last_error="permanent failure",
            exit_code=2,
        )

        response = self.client.post(
            f"/api/migrations/transfer/replay/{run.run_id}",
            {},
            format="json",
            HTTP_X_API_KEY="operator-test-key",
        )

        self.assertEqual(response.status_code, 200)
        run.refresh_from_db()
        self.assertEqual(run.status, TransferRun.STATUS_QUEUED)
        self.assertEqual(run.step, TransferRun.STEP_QUEUED)
        self.assertEqual(run.retry_count, 0)
        self.assertEqual(run.last_error, "")

    @override_settings(RBAC_OPERATOR_KEYS=["operator-test-key"])
    def test_transfer_replay_rejects_running_run(self):
        run = TransferRun.objects.create(
            run_id="run-running",
            status=TransferRun.STATUS_RUNNING,
            step=TransferRun.STEP_TRANSFER,
            command=["python", "manage.py", "transfer_render_to_railway", "--dry-run"],
            options={"mode": "queue"},
        )

        response = self.client.post(
            f"/api/migrations/transfer/replay/{run.run_id}",
            {},
            format="json",
            HTTP_X_API_KEY="operator-test-key",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json())

    @override_settings(
        TRANSFER_WORKER_LIMIT=7,
        TRANSFER_WORKER_POLL_INTERVAL_SECONDS=9,
        TRANSFER_WORKER_LEASE_TTL_SECONDS=180,
        TRANSFER_WORKER_HEARTBEAT_INTERVAL_SECONDS=21,
        TRANSFER_WORKSPACE_CONCURRENCY_CAP=2,
        TRANSFER_QUEUE_AGING_WINDOW_SECONDS=120,
        TRANSFER_QUEUE_MAX_AGING_BOOST=6,
        TRANSFER_ALERT_DEAD_LETTER_THRESHOLD=1,
        TRANSFER_ALERT_RETRYABLE_THRESHOLD=1,
        TRANSFER_ALERT_STALE_LEASE_THRESHOLD=1,
    )
    def test_transfer_metrics_returns_summary_and_workspace_counts(self):
        workspace_a = Workspace.objects.create(name="A", owner_email="a@example.com")
        workspace_b = Workspace.objects.create(name="B", owner_email="b@example.com")

        TransferRun.objects.create(
            run_id="metrics-running-a",
            workspace=workspace_a,
            status=TransferRun.STATUS_RUNNING,
            step=TransferRun.STEP_TRANSFER,
            command=["python", "manage.py"],
            lease_owner="worker",
            lease_expires_at=timezone.now() + timezone.timedelta(minutes=2),
            heartbeat_at=timezone.now(),
        )
        TransferRun.objects.create(
            run_id="metrics-queued-a",
            workspace=workspace_a,
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py"],
        )
        TransferRun.objects.create(
            run_id="metrics-dead-b",
            workspace=workspace_b,
            status=TransferRun.STATUS_DEAD_LETTER,
            command=["python", "manage.py"],
        )
        TransferRun.objects.create(
            run_id="metrics-retryable-b",
            workspace=workspace_b,
            status=TransferRun.STATUS_RETRYABLE,
            command=["python", "manage.py"],
        )
        TransferRun.objects.create(
            run_id="metrics-stale-a",
            workspace=workspace_a,
            status=TransferRun.STATUS_RUNNING,
            step=TransferRun.STEP_TRANSFER,
            command=["python", "manage.py"],
            lease_owner="worker-dead",
            lease_expires_at=timezone.now() - timezone.timedelta(minutes=1),
            heartbeat_at=timezone.now() - timezone.timedelta(minutes=2),
        )

        response = self.client.get(
            "/api/migrations/transfer/metrics",
            HTTP_X_API_KEY="viewer-test-key",
            HTTP_X_ACCOUNT_EMAIL="a@example.com",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["summary"]["running"], 1)
        self.assertEqual(body["summary"]["queued"], 1)
        self.assertEqual(body["summary"]["deadLetter"], 1)
        self.assertEqual(body["schedulingPolicy"]["workerBatchLimit"], 7)
        self.assertEqual(body["schedulingPolicy"]["pollIntervalSeconds"], 9)
        self.assertEqual(body["schedulingPolicy"]["leaseTtlSeconds"], 180)
        self.assertEqual(body["schedulingPolicy"]["heartbeatIntervalSeconds"], 21)
        self.assertEqual(body["schedulingPolicy"]["workspaceConcurrencyCap"], 2)
        self.assertEqual(body["schedulingPolicy"]["agingWindowSeconds"], 120)
        self.assertEqual(body["schedulingPolicy"]["maxAgingBoost"], 6)
        self.assertTrue(body["alerts"]["deadLetter"]["active"])
        self.assertTrue(body["alerts"]["retryableBacklog"]["active"])
        self.assertTrue(body["alerts"]["staleLeases"]["active"])
        self.assertEqual(body["workspace"]["name"], "a@example.com workspace")
        self.assertEqual(body["workspace"]["running"], 0)
        self.assertEqual(body["workspace"]["queued"], 0)
        self.assertEqual(body["workspace"]["deadLetter"], 0)

    @override_settings(TRANSFER_QUEUE_AGING_WINDOW_SECONDS=300, TRANSFER_QUEUE_MAX_AGING_BOOST=10)
    def test_transfer_history_includes_effective_queue_priority(self):
        run = TransferRun.objects.create(
            run_id="priority-history",
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py"],
            options={"queuePriority": 4},
        )
        TransferRun.objects.filter(id=run.id).update(created_at=timezone.now() - timezone.timedelta(minutes=20))

        response = self.client.get("/api/migrations/transfer/history?limit=1", HTTP_X_API_KEY="viewer-test-key")

        self.assertEqual(response.status_code, 200)
        item = response.json()["runs"][0]
        self.assertEqual(item["queuePriority"], 4)
        self.assertGreaterEqual(item["queueAgeBoost"], 4)
        self.assertEqual(item["queueEffectivePriority"], item["queuePriority"] + item["queueAgeBoost"])
        self.assertEqual(item["agingWindowSeconds"], 300)
        self.assertEqual(item["maxAgingBoost"], 10)

    @override_settings(TRANSFER_QUEUE_AGING_WINDOW_SECONDS=300, TRANSFER_QUEUE_MAX_AGING_BOOST=10)
    def test_transfer_status_includes_effective_queue_priority(self):
        run = TransferRun.objects.create(
            run_id="priority-status",
            status=TransferRun.STATUS_QUEUED,
            command=["python", "manage.py"],
            options={"queuePriority": 2},
        )
        TransferRun.objects.filter(id=run.id).update(created_at=timezone.now() - timezone.timedelta(minutes=10))

        previous = dict(_TRANSFER_STATE)
        _TRANSFER_STATE.update({"id": run.run_id, "process": None, "startedAt": "", "command": [], "logPath": ""})
        try:
            payload = _transfer_status_payload()
        finally:
            _TRANSFER_STATE.clear()
            _TRANSFER_STATE.update(previous)

        self.assertEqual(payload["queuePriority"], 2)
        self.assertGreaterEqual(payload["queueAgeBoost"], 2)
        self.assertEqual(payload["queueEffectivePriority"], payload["queuePriority"] + payload["queueAgeBoost"])
