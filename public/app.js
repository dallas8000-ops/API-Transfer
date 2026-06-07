"use strict";

const API_BASE = "/api/migrations";

const SAMPLE_SPEC = {
  appName: "demo-app",
  sourceProvider: "render",
  targetProvider: "railway",
  services: [
    {
      name: "web",
      runtime: "node",
      startCommand: "node server.js",
      region: "oregon",
      environment: { NODE_ENV: "production" },
      secrets: [{ key: "API_KEY", value: "replace-me" }]
    }
  ],
  domains: [{ host: "demo-app.example.com", tlsRequired: true }],
  databases: [{ name: "primary", engine: "postgres", version: "16" }],
  metadata: {
    requestedBy: "ui-user",
    requestedAt: new Date().toISOString(),
    environment: "stage"
  }
};

let currentPlan = null;
let currentSpec = null;
let currentProject = null;
let lastReport = null;

function $(id) {
  return document.getElementById(id);
}

function authHeaders() {
  const headers = { "Content-Type": "application/json" };
  const key = $("apiKey").value.trim();
  if (key) {
    headers["x-api-key"] = key;
  }
  return headers;
}

async function postJson(path, body) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}

async function getJson(path) {
  const response = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}

function show(el, value) {
  el.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

async function onDiscover() {
  const out = $("discoverOutput");
  try {
    show(out, "Discovering...");
    const data = await postJson("/discover", {
      provider: $("discoverProvider").value,
      appIdentifier: $("discoverApp").value.trim()
    });
    show(out, data);
    if (data.spec) {
      $("specInput").value = JSON.stringify(data.spec, null, 2);
    }
  } catch (err) {
    show(out, `Error: ${err.message}`);
  }
}

async function onPlan() {
  const out = $("planOutput");
  try {
    show(out, "Planning...");
    currentSpec = JSON.parse($("specInput").value);
    const data = await postJson("/plan", { spec: currentSpec });
    currentPlan = data.plan;
    show(out, data);
    renderPlanSummary();
    $("applyBtn").disabled = false;
  } catch (err) {
    show(out, `Error: ${err.message}`);
    $("applyBtn").disabled = true;
  }
}

function renderPlanSummary() {
  if (!currentPlan) {
    $("planSummary").textContent = "No plan yet.";
    return;
  }
  const riskClass = currentPlan.riskScore > 60 ? "err" : currentPlan.riskScore > 30 ? "warn" : "ok";
  const warnings = currentPlan.warnings.length
    ? `<ul>${currentPlan.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}</ul>`
    : "<em>None</em>";
  $("planSummary").innerHTML =
    `<strong>${escapeHtml(currentPlan.summary)}</strong><br />` +
    `Risk: <span class="badge ${riskClass}">${currentPlan.riskScore}</span> ` +
    `Confidence: <span class="badge ok">${currentPlan.confidence}</span><br />` +
    `<strong>Warnings:</strong> ${warnings}`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function onApply() {
  const out = $("applyOutput");
  try {
    if (!currentPlan || !currentSpec) {
      throw new Error("Create a plan first");
    }
    show(out, "Applying...");
    const data = await postJson("/apply", {
      spec: currentSpec,
      plan: currentPlan,
      approvedBy: $("approvedBy").value.trim()
    });
    show(out, data);
  } catch (err) {
    show(out, `Error: ${err.message}`);
  }
}

async function onAudit() {
  const out = $("auditOutput");
  try {
    show(out, "Loading...");
    const data = await getJson("/audit");
    show(out, data);
  } catch (err) {
    show(out, `Error: ${err.message}`);
  }
}

async function onDeploy() {
  const out = $("deployOutput");
  const live = $("deployLive");
  try {
    live.innerHTML = "";
    show(out, "Deploying... detecting framework and provisioning resources.");
    const files = $("deployFiles")
      .value.split("\n")
      .map((f) => f.trim())
      .filter((f) => f.length > 0);

    const body = {
      appName: $("deployAppName").value.trim(),
      targetProvider: $("deployProvider").value,
      domain: $("deployDomain").value.trim() || undefined,
      targetEnvironment: $("deployEnv").value,
      files,
      environment: {},
      secrets: [],
      enableStripe: $("deployStripe").checked,
      enableMonitoring: $("deployMonitoring").checked,
      enableBackups: $("deployBackups").checked,
      requestedBy: $("approvedBy").value.trim() || "ui-user"
    };

    const data = await postJson("/deploy", body);
    show(out, data);

    const result = data.result;
    if (result && result.liveUrl) {
      const statusClass = result.succeeded ? "ok" : "warn";
      live.innerHTML =
        `<p>Framework: <span class="badge ok">${escapeHtml(result.framework.framework)}</span> ` +
        `(${result.framework.confidence}% confidence)</p>` +
        `<p>Status: <span class="badge ${statusClass}">${result.succeeded ? "LIVE" : "NEEDS ATTENTION"}</span></p>` +
        `<p>Live URL: <a href="${encodeURI(result.liveUrl)}" target="_blank" rel="noopener">${escapeHtml(result.liveUrl)}</a></p>`;
    }
  } catch (err) {
    show(out, `Error: ${err.message}`);
  }
}

function buildProjectFromForm() {
  const files = $("diagFiles")
    .value.split("\n")
    .map((f) => f.trim())
    .filter((f) => f.length > 0);

  const environment = {};
  $("diagEnvVars")
    .value.split("\n")
    .map((line) => line.trim())
    .filter((line) => line.includes("="))
    .forEach((line) => {
      const idx = line.indexOf("=");
      const key = line.slice(0, idx).trim();
      const value = line.slice(idx + 1).trim();
      if (key) environment[key] = value;
    });

  return {
    appName: $("diagAppName").value.trim(),
    targetProvider: $("diagProvider").value,
    domain: $("diagDomain").value.trim() || undefined,
    targetEnvironment: $("diagEnv").value,
    files,
    environment,
    secrets: [],
    enableStripe: $("diagStripe").checked,
    enableMonitoring: $("diagMonitoring").checked,
    enableBackups: $("diagBackups").checked,
    requestedBy: $("approvedBy").value.trim() || "ui-user"
  };
}

const SEVERITY_CLASS = {
  critical: "err",
  high: "err",
  medium: "warn",
  low: "warn",
  info: "ok"
};

function renderReport(report) {
  const s = report.summary;
  const scoreClass = s.healthScore >= 80 ? "ok" : s.healthScore >= 50 ? "warn" : "err";
  const counts = Object.entries(s.bySeverity)
    .filter(([, n]) => n > 0)
    .map(([sev, n]) => `<span class="badge ${SEVERITY_CLASS[sev]}">${sev}: ${n}</span>`)
    .join(" ");
  const list = report.issues.length
    ? `<ul>${report.issues
        .map(
          (i) =>
            `<li><span class="badge ${SEVERITY_CLASS[i.severity]}">${i.severity}</span> ` +
            `<strong>${escapeHtml(i.title)}</strong>${i.autoFixable ? ' <span class="badge ok">auto-fix</span>' : ""}` +
            `<br /><small>${escapeHtml(i.recommendation)}</small></li>`
        )
        .join("")}</ul>`
    : "<em>No issues found.</em>";
  $("diagSummary").innerHTML =
    `<p>Framework: <span class="badge ok">${escapeHtml(report.framework.framework)}</span> ` +
    `Health: <span class="badge ${scoreClass}">${s.healthScore}/100</span></p>` +
    `<p>${counts || "<em>clean</em>"} &middot; ${s.autoFixable} auto-fixable</p>` +
    list;
}

async function onDiagnose() {
  const out = $("diagOutput");
  try {
    show(out, "Analyzing project settings...");
    currentProject = buildProjectFromForm();
    const data = await postJson("/diagnose", currentProject);
    lastReport = data.report;
    renderReport(lastReport);
    show(out, data);
    $("autoFixBtn").disabled = lastReport.summary.autoFixable === 0;
  } catch (err) {
    show(out, `Error: ${err.message}`);
    $("autoFixBtn").disabled = true;
  }
}

async function onAutoFix() {
  const out = $("diagOutput");
  try {
    if (!currentProject) throw new Error("Run Diagnose first");
    show(out, "Applying safe auto-fixes...");
    const data = await postJson("/diagnose/fix", { project: currentProject });
    if (data.result && data.result.residualReport) {
      renderReport(data.result.residualReport);
    }
    show(out, data);
  } catch (err) {
    show(out, `Error: ${err.message}`);
  }
}

function init() {
  $("specInput").value = JSON.stringify(SAMPLE_SPEC, null, 2);
  $("discoverBtn").addEventListener("click", onDiscover);
  $("planBtn").addEventListener("click", onPlan);
  $("applyBtn").addEventListener("click", onApply);
  $("auditBtn").addEventListener("click", onAudit);
  $("deployBtn").addEventListener("click", onDeploy);
  $("diagnoseBtn").addEventListener("click", onDiagnose);
  $("autoFixBtn").addEventListener("click", onAutoFix);
}

document.addEventListener("DOMContentLoaded", init);
