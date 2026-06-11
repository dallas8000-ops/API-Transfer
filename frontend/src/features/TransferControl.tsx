import { useEffect, useState } from "react";
import {
  getTransferHistory,
  getTransferMetrics,
  getTransferStatus,
  replayTransfer,
  startTransfer,
  stopTransfer,
  type TransferMetricsResponse,
  type TransferRunStatus,
  type TransferStartRequest,
} from "../api";
import { Card, Field, Output, StatusBadge } from "../components/ui";
import type { ImportedProject } from "./GitHubImport";

function parseOnly(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function summarizeStatus(run: TransferRunStatus | null): string {
  if (!run) return "No transfer run recorded.";
  if (run.running) return `Running since ${run.startedAt || "unknown"}`;
  if (run.id) return `Last run exit code: ${run.exitCode ?? "unknown"}`;
  return "No transfer run recorded.";
}

function runStateLabel(run: TransferRunStatus): string {
  if (run.running) return "running";
  if (run.status) return run.status;
  if (run.exitCode === 0) return "succeeded";
  if (run.exitCode === null || run.exitCode === undefined) return "idle";
  return "failed";
}

function formatWhen(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

type StepCheckpoint = {
  updatedAt?: string;
  details?: Record<string, unknown>;
};

function getCheckpoint(run: TransferRunStatus, step: string): StepCheckpoint {
  const state = run.stepState || {};
  const value = state[step];
  const checkpoint: StepCheckpoint =
    typeof value === "object" && value !== null ? value : {};
  return checkpoint;
}

function isReplayedFromCheckpoint(run: TransferRunStatus): boolean {
  const verify = getCheckpoint(run, "verify");
  const details = verify.details || {};
  return Boolean(details.replayedFrom || details.checkpoint);
}

function replaySource(run: TransferRunStatus): string {
  const verify = getCheckpoint(run, "verify");
  const details = verify.details || {};
  const source = details.replayedFrom;
  return typeof source === "string" && source ? source : "-";
}

function checkpointUpdated(run: TransferRunStatus, step: string): string {
  const cp = getCheckpoint(run, step);
  return formatWhen(cp.updatedAt);
}

function TransferMetricsPanel({ metrics }: Readonly<{ metrics: TransferMetricsResponse | null }>) {
  if (!metrics) return null;

  return (
    <div className="plan-summary">
      <div className="provider-head">
        <strong>Queue metrics</strong>
        <span className="muted">{formatWhen(metrics.generatedAt)}</span>
      </div>
      <div className="history-meta">
        <span className="muted">Global running</span>
        <strong>{metrics.summary.running}</strong>
        <span className="muted">Global queued</span>
        <strong>{metrics.summary.queued}</strong>
        <span className="muted">Global retryable</span>
        <strong>{metrics.summary.retryable}</strong>
        <span className="muted">Global dead letter</span>
        <strong>{metrics.summary.deadLetter}</strong>
        <span className="muted">Workspace</span>
        <strong>{metrics.workspace.name}</strong>
        <span className="muted">Workspace running</span>
        <strong>{metrics.workspace.running}</strong>
        <span className="muted">Workspace queued</span>
        <strong>{metrics.workspace.queued}</strong>
        <span className="muted">Policy batch limit</span>
        <strong>{metrics.schedulingPolicy.workerBatchLimit}</strong>
        <span className="muted">Policy workspace cap</span>
        <strong>{metrics.schedulingPolicy.workspaceConcurrencyCap}</strong>
        <span className="muted">Policy aging window (sec)</span>
        <strong>{metrics.schedulingPolicy.agingWindowSeconds}</strong>
        <span className="muted">Policy max aging boost</span>
        <strong>{metrics.schedulingPolicy.maxAgingBoost}</strong>
        <span className="muted">Alert dead letter</span>
        <strong>
          {metrics.alerts.deadLetter.active
            ? `active (${metrics.alerts.deadLetter.count}/${metrics.alerts.deadLetter.threshold})`
            : `ok (${metrics.alerts.deadLetter.count}/${metrics.alerts.deadLetter.threshold})`}
        </strong>
        <span className="muted">Alert retry backlog</span>
        <strong>
          {metrics.alerts.retryableBacklog.active
            ? `active (${metrics.alerts.retryableBacklog.count}/${metrics.alerts.retryableBacklog.threshold})`
            : `ok (${metrics.alerts.retryableBacklog.count}/${metrics.alerts.retryableBacklog.threshold})`}
        </strong>
        <span className="muted">Alert stale leases</span>
        <strong>
          {metrics.alerts.staleLeases.active
            ? `active (${metrics.alerts.staleLeases.count}/${metrics.alerts.staleLeases.threshold})`
            : `ok (${metrics.alerts.staleLeases.count}/${metrics.alerts.staleLeases.threshold})`}
        </strong>
      </div>
    </div>
  );
}

type TransferHistoryPanelProps = {
  history: TransferRunStatus[];
  historyLimit: number;
  historyBusy: boolean;
  historyCursor: string | null;
  selectedRun: TransferRunStatus | null;
  showReplayedOnly: boolean;
  onSelectRun: (run: TransferRunStatus) => void;
  onLimitChange: (value: number) => void;
  onToggleReplayedOnly: (enabled: boolean) => void;
  onRefreshHistory: () => void;
  onLoadOlderHistory: () => void;
  onReplayRun: (runId: string) => void;
  replayBusy: boolean;
};

function TransferHistoryPanel({
  history,
  historyLimit,
  historyBusy,
  historyCursor,
  selectedRun,
  showReplayedOnly,
  onSelectRun,
  onLimitChange,
  onToggleReplayedOnly,
  onRefreshHistory,
  onLoadOlderHistory,
  onReplayRun,
  replayBusy,
}: Readonly<TransferHistoryPanelProps>) {
  if (!history.length) return null;

  return (
    <div className="plan-summary">
      <div className="provider-head">
        <strong>Recent runs</strong>
        <div className="history-tools">
          <span className="muted">{history.length}</span>
          <select value={String(historyLimit)} onChange={(e) => onLimitChange(Number(e.target.value))}>
            <option value="8">8</option>
            <option value="20">20</option>
            <option value="50">50</option>
          </select>
          <label className="inline history-filter-inline">
            <input
              type="checkbox"
              checked={showReplayedOnly}
              onChange={(e) => onToggleReplayedOnly(e.target.checked)}
            />
            <span>Replayed only</span>
          </label>
        </div>
      </div>
      {history.map((run) => (
        <button
          key={run.id}
          type="button"
          className={`history-row ${selectedRun?.id === run.id ? "active" : ""}`}
          onClick={() => onSelectRun(run)}
        >
          <span className="muted">{run.id}</span>
          <div className="history-row-badges">
            {isReplayedFromCheckpoint(run) ? <span className="checkpoint-badge">replayed</span> : null}
            <StatusBadge
              ok={runStateLabel(run) === "running" || runStateLabel(run) === "succeeded"}
              label={runStateLabel(run)}
            />
          </div>
        </button>
      ))}
      <div className="toggles" style={{ marginTop: "10px" }}>
        <button className="btn btn-outline btn-sm" onClick={onRefreshHistory} disabled={historyBusy}>
          Newest
        </button>
        <button className="btn btn-outline btn-sm" onClick={onLoadOlderHistory} disabled={historyBusy || !historyCursor}>
          Load older
        </button>
      </div>
      {selectedRun ? (
        <div className="history-drawer">
          <div className="provider-head">
            <strong>Run details</strong>
            <StatusBadge
              ok={runStateLabel(selectedRun) === "running" || runStateLabel(selectedRun) === "succeeded"}
              label={runStateLabel(selectedRun)}
            />
          </div>
          <div className="history-meta">
            <span className="muted">ID</span>
            <strong>{selectedRun.id}</strong>
            <span className="muted">Mode</span>
            <strong>{selectedRun.mode || "-"}</strong>
            <span className="muted">Started</span>
            <strong>{formatWhen(selectedRun.startedAt)}</strong>
            <span className="muted">Finished</span>
            <strong>{formatWhen(selectedRun.finishedAt)}</strong>
            <span className="muted">Exit code</span>
            <strong>{selectedRun.exitCode ?? "-"}</strong>
            <span className="muted">Queue priority</span>
            <strong>{selectedRun.queuePriority ?? 0}</strong>
            <span className="muted">Aging boost</span>
            <strong>{selectedRun.queueAgeBoost ?? 0}</strong>
            <span className="muted">Effective priority</span>
            <strong>{selectedRun.queueEffectivePriority ?? selectedRun.queuePriority ?? 0}</strong>
            <span className="muted">Checkpoint replay</span>
            <strong>{isReplayedFromCheckpoint(selectedRun) ? "yes" : "no"}</strong>
            <span className="muted">Replay source</span>
            <strong>{replaySource(selectedRun)}</strong>
            <span className="muted">Transfer checkpoint</span>
            <strong>{checkpointUpdated(selectedRun, "transfer")}</strong>
            <span className="muted">Verify checkpoint</span>
            <strong>{checkpointUpdated(selectedRun, "verify")}</strong>
          </div>
          {selectedRun.command?.length ? <Output value={selectedRun.command.join(" ")} /> : null}
          {selectedRun.options ? <Output value={selectedRun.options} /> : null}
          {selectedRun.logTail ? <Output value={selectedRun.logTail} /> : null}
          <div className="toggles" style={{ marginTop: "10px" }}>
            <button
              className="btn btn-outline btn-sm"
              disabled={
                replayBusy ||
                !["failed", "dead_letter", "stopped"].includes((selectedRun.status || "").toLowerCase())
              }
              onClick={() => onReplayRun(selectedRun.id)}
            >
              Replay run
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function TransferControl({
  importedProject,
  selectedApp,
}: Readonly<{ importedProject?: ImportedProject | null; selectedApp?: { provider: string; app: { name: string } } | null }>) {
  const [mode, setMode] = useState<"queue" | "demand">("demand");
  const [only, setOnly] = useState(selectedApp?.app.name || importedProject?.appName || "");
  const [limit, setLimit] = useState("10");
  const [queuePriority, setQueuePriority] = useState("0");
  const [redeployExisting, setRedeployExisting] = useState(false);
  const [verify, setVerify] = useState(true);
  const [verifyTimeout, setVerifyTimeout] = useState("240");
  const [verifyInterval, setVerifyInterval] = useState("10");
  const [serviceTimeout, setServiceTimeout] = useState("180");
  const [allowOverlap, setAllowOverlap] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [status, setStatus] = useState<TransferRunStatus | null>(null);
  const [history, setHistory] = useState<TransferRunStatus[]>([]);
  const [historyLimit, setHistoryLimit] = useState(8);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [selectedRun, setSelectedRun] = useState<TransferRunStatus | null>(null);
  const [showReplayedOnly, setShowReplayedOnly] = useState(false);
  const [replayBusy, setReplayBusy] = useState(false);
  const [metrics, setMetrics] = useState<TransferMetricsResponse | null>(null);
  const [out, setOut] = useState<unknown>("");
  const [busy, setBusy] = useState(false);

  async function refreshStatus() {
    try {
      const data = await getTransferStatus();
      setStatus(data.run);
    } catch (error) {
      setOut(`Error: ${(error as Error).message}`);
    }
  }

  async function refreshHistory() {
    try {
      const data = await getTransferHistory(historyLimit);
      setHistory(data.runs || []);
      setHistoryCursor(data.nextCursor || null);
      setSelectedRun((prev) => prev ?? data.runs?.[0] ?? null);
    } catch (error) {
      setOut(`Error: ${(error as Error).message}`);
    }
  }

  async function refreshMetrics() {
    try {
      const data = await getTransferMetrics();
      setMetrics(data);
    } catch (error) {
      setOut(`Error: ${(error as Error).message}`);
    }
  }

  async function loadOlderHistory() {
    if (!historyCursor) return;
    try {
      setHistoryBusy(true);
      const data = await getTransferHistory(historyLimit, historyCursor);
      setHistory((prev) => [...prev, ...(data.runs || [])]);
      setHistoryCursor(data.nextCursor || null);
    } catch (error) {
      setOut(`Error: ${(error as Error).message}`);
    } finally {
      setHistoryBusy(false);
    }
  }

  async function refreshAll() {
    await Promise.all([refreshStatus(), refreshHistory(), refreshMetrics()]);
  }

  useEffect(() => {
    void refreshAll();
  }, [historyLimit]);

  useEffect(() => {
    if (!status?.running) return undefined;
    const timer = globalThis.setInterval(() => {
      void refreshAll();
    }, 5000);
    return () => globalThis.clearInterval(timer);
  }, [status?.running]);

  useEffect(() => {
    if (selectedApp?.app.name) {
      setOnly(selectedApp.app.name);
      return;
    }
    if (importedProject?.appName) {
      setOnly(importedProject.appName);
    }
  }, [importedProject, selectedApp]);

  const visibleHistory = showReplayedOnly ? history.filter((run) => isReplayedFromCheckpoint(run)) : history;

  useEffect(() => {
    if (!visibleHistory.length) {
      setSelectedRun(null);
      return;
    }
    setSelectedRun((prev) => {
      if (prev && visibleHistory.some((run) => run.id === prev.id)) {
        return prev;
      }
      return visibleHistory[0];
    });
  }, [showReplayedOnly, history]);

  function buildPayload(): TransferStartRequest {
    const parsedQueuePriority = Number(queuePriority);
    const normalizedQueuePriority = Number.isFinite(parsedQueuePriority)
      ? Math.max(0, Math.min(100, Math.trunc(parsedQueuePriority)))
      : 0;
    const payload: TransferStartRequest = {
      mode,
      queuePriority: normalizedQueuePriority,
      redeployExisting,
      verify,
      verifyTimeout: Number(verifyTimeout),
      verifyInterval: Number(verifyInterval),
      serviceTimeout: Number(serviceTimeout),
      allowOverlap,
      dryRun,
    };
    if (mode === "demand") {
      payload.only = parseOnly(only);
    } else {
      payload.limit = Number(limit);
    }
    return payload;
  }

  async function onStart() {
    try {
      setBusy(true);
      setOut("Starting transfer...");
      const data = await startTransfer(buildPayload());
      setStatus(data.run);
      void refreshHistory();
      setOut(data);
    } catch (error) {
      setOut(`Error: ${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onStop() {
    try {
      setBusy(true);
      setOut("Stopping transfer...");
      const data = await stopTransfer();
      if (data.run) {
        setStatus(data.run);
      }
      void refreshHistory();
      setOut(data);
    } catch (error) {
      setOut(`Error: ${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onReplayRun(runId: string) {
    try {
      setReplayBusy(true);
      setOut(`Replaying run ${runId}...`);
      const data = await replayTransfer(runId);
      setSelectedRun(data.run);
      await refreshAll();
      setOut(data);
    } catch (error) {
      setOut(`Error: ${(error as Error).message}`);
    } finally {
      setReplayBusy(false);
    }
  }

  return (
    <Card title="Transfer control" hint="Start, stop, and monitor Render to Railway transfer runs from the console.">
      <div className="row">
        <Field label="Execution mode">
          <select value={mode} onChange={(e) => setMode(e.target.value as "queue" | "demand")}>
            <option value="queue">queue</option>
            <option value="demand">demand</option>
          </select>
        </Field>
        {mode === "queue" ? (
          <Field label="Queue limit">
            <input value={limit} onChange={(e) => setLimit(e.target.value)} inputMode="numeric" />
          </Field>
        ) : (
          <Field label="Demand targets">
            <input
              value={only}
              onChange={(e) => setOnly(e.target.value)}
              placeholder="specwright-api, BLOG-2"
            />
          </Field>
        )}
      </div>
      <div className="row">
        <Field label="Verify timeout (sec)">
          <input value={verifyTimeout} onChange={(e) => setVerifyTimeout(e.target.value)} inputMode="numeric" />
        </Field>
        <Field label="Service timeout (sec)">
          <input value={serviceTimeout} onChange={(e) => setServiceTimeout(e.target.value)} inputMode="numeric" />
        </Field>
      </div>
      <div className="row">
        <Field label="Verify interval (sec)">
          <input value={verifyInterval} onChange={(e) => setVerifyInterval(e.target.value)} inputMode="numeric" />
        </Field>
        <Field label="Queue priority (0-100)">
          <input value={queuePriority} onChange={(e) => setQueuePriority(e.target.value)} inputMode="numeric" />
        </Field>
      </div>
      <div className="row">
        <Field label="Current run">
          <div className="plan-summary">
            <div className="provider-head">
              <strong>{status?.id || "none"}</strong>
              <StatusBadge ok={Boolean(status?.running)} label={status?.running ? "running" : "idle"} />
            </div>
            <p className="muted">{summarizeStatus(status)}</p>
          </div>
        </Field>
      </div>
      <div className="toggles">
        <label className="inline">
          <input type="checkbox" checked={redeployExisting} onChange={(e) => setRedeployExisting(e.target.checked)} />{" "}
          Redeploy existing services
        </label>
        <label className="inline">
          <input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} />{" "}
          Verify deploy status
        </label>
        <label className="inline">
          <input type="checkbox" checked={allowOverlap} onChange={(e) => setAllowOverlap(e.target.checked)} />{" "}
          Allow overlap
        </label>
        <label className="inline">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />{" "}
          Dry run
        </label>
      </div>
      <div className="toggles">
        <button className="btn btn-primary" onClick={onStart} disabled={busy || Boolean(status?.running)}>
          Start transfer
        </button>
        <button className="btn btn-outline" onClick={() => void refreshAll()} disabled={busy}>
          Refresh status
        </button>
        <button className="btn btn-outline" onClick={onStop} disabled={busy || !status?.running}>
          Stop transfer
        </button>
      </div>
      {status?.command?.length ? <Output value={status.command.join(" ")} /> : null}
      {status?.logTail ? <Output value={status.logTail} /> : null}
      <TransferMetricsPanel metrics={metrics} />
      <TransferHistoryPanel
        history={visibleHistory}
        historyLimit={historyLimit}
        historyBusy={historyBusy}
        historyCursor={historyCursor}
        selectedRun={selectedRun}
        showReplayedOnly={showReplayedOnly}
        onSelectRun={setSelectedRun}
        onLimitChange={(value) => {
          setHistoryLimit(value);
          setHistoryCursor(null);
        }}
        onToggleReplayedOnly={setShowReplayedOnly}
        onRefreshHistory={() => void refreshHistory()}
        onLoadOlderHistory={() => void loadOlderHistory()}
        onReplayRun={(runId) => void onReplayRun(runId)}
        replayBusy={replayBusy}
      />
      <Output value={out} />
    </Card>
  );
}
