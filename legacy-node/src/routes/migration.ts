import express from "express";
import { randomUUID } from "node:crypto";
import { redactSensitiveValues } from "../security/redaction";
import { logger } from "../logger";
import { applyPlanRequestSchema, createPlanRequestSchema, migrationSpecSchema, deploymentRequestSchema, diagnosisRequestSchema, diagnosisFixRequestSchema } from "./schemas";
import { applyPlan, generatePlan, rollbackPlan } from "../services/migrationService";
import { auditLog } from "../services/auditLog";
import { getAdapter } from "../adapters/registry";
import { ProviderType } from "../domain/types";
import { requireRole } from "../middleware/rbac";
import { createTerraformPlan, applyTerraformPlan, TerraformResource } from "../services/terraformService";
import { detectFramework } from "../services/frameworkDetector";
import { runDeploymentPipeline } from "../services/deploymentPipeline";
import { analyzeProject, applyFixes } from "../services/diagnosticsEngine";

const SUPPORTED_PROVIDERS: ProviderType[] = ["render", "railway", "fly", "kong", "terraform", "supabase"];

const encryptedPlanStore = new Map<string, Record<string, { iv: string; authTag: string; ciphertext: string }>>();

export function migrationRouter() {
  const router = express.Router();

  router.post("/discover", requireRole("viewer"), async (req, res, next) => {
    try {
      const provider = typeof req.body?.provider === "string" ? req.body.provider : "";
      const appIdentifier = typeof req.body?.appIdentifier === "string" ? req.body.appIdentifier : "";

      if (!SUPPORTED_PROVIDERS.includes(provider as ProviderType)) {
        res.status(400).json({ error: `Unsupported provider. Use one of: ${SUPPORTED_PROVIDERS.join(", ")}` });
        return;
      }
      if (!appIdentifier) {
        res.status(400).json({ error: "appIdentifier is required" });
        return;
      }

      const adapter = getAdapter(provider as ProviderType);
      const snapshot = await adapter.discover(appIdentifier);
      const spec = await adapter.toCanonical(snapshot);

      logger.info({ provider, appIdentifier, live: snapshot.raw.live === true }, "Provider discovery completed");

      res.status(200).json({
        snapshot: redactSensitiveValues(snapshot),
        spec: redactSensitiveValues(spec)
      });
    } catch (error) {
      next(error);
    }
  });

  router.post("/plan", requireRole("operator"), async (req, res, next) => {
    try {
      const parsed = createPlanRequestSchema.parse(req.body);
      const { plan, encryptedSecrets } = await generatePlan(parsed.spec);
      encryptedPlanStore.set(plan.planId, encryptedSecrets);

      logger.info(
        { payload: redactSensitiveValues(parsed), planId: plan.planId },
        "Migration plan generated"
      );

      res.status(200).json({
        plan,
        note: "Secrets are encrypted in-memory and never returned in plaintext."
      });
    } catch (error) {
      next(error);
    }
  });

  router.post("/apply", requireRole("admin"), async (req, res, next) => {
    try {
      const parsed = applyPlanRequestSchema.parse(req.body);
      const encryptedSecrets = encryptedPlanStore.get(parsed.plan.planId);

      if (!encryptedSecrets) {
        res.status(404).json({
          error: "No encrypted secret state found for this plan ID. Recreate the plan first."
        });
        return;
      }

      const result = await applyPlan({
        spec: parsed.spec,
        plan: parsed.plan,
        encryptedSecrets,
        approvedBy: parsed.approvedBy
      });

      encryptedPlanStore.delete(parsed.plan.planId);

      logger.info(
        { planId: parsed.plan.planId, approvedBy: parsed.approvedBy },
        "Migration apply executed"
      );

      res.status(200).json({ result });
    } catch (error) {
      next(error);
    }
  });

  router.post("/rollback", requireRole("admin"), async (req, res, next) => {
    try {
      const planId = typeof req.body?.planId === "string" ? req.body.planId : "";
      const actor = typeof req.body?.actor === "string" ? req.body.actor : "";

      if (!planId) {
        res.status(400).json({ error: "planId is required" });
        return;
      }

      const result = await rollbackPlan(planId, actor);
      logger.info({ planId, actor }, "Migration rollback executed");
      res.status(200).json({ result });
    } catch (error) {
      next(error);
    }
  });

  router.post("/terraform/plan", requireRole("operator"), (req, res, next) => {
    try {
      const spec = migrationSpecSchema.parse(req.body?.spec);
      const currentStateRaw = Array.isArray(req.body?.currentState) ? req.body.currentState : [];
      const currentState = currentStateRaw as TerraformResource[];

      const planId = randomUUID();
      const plan = createTerraformPlan(planId, spec, currentState);

      auditLog.record("plan", req.auth?.actor ?? "unknown", { kind: "terraform", summary: plan.summary }, planId);
      logger.info({ planId, summary: plan.summary }, "Terraform plan generated");

      res.status(200).json({ plan });
    } catch (error) {
      next(error);
    }
  });

  router.post("/terraform/apply", requireRole("admin"), (req, res, next) => {
    try {
      const spec = migrationSpecSchema.parse(req.body?.spec);
      const currentStateRaw = Array.isArray(req.body?.currentState) ? req.body.currentState : [];
      const currentState = currentStateRaw as TerraformResource[];
      const submittedHash = typeof req.body?.integrityHash === "string" ? req.body.integrityHash : "";
      const planId = typeof req.body?.planId === "string" ? req.body.planId : "";

      if (!planId || !submittedHash) {
        res.status(400).json({ error: "planId and integrityHash are required" });
        return;
      }

      // Re-derive the plan deterministically and verify it matches what was approved.
      const plan = createTerraformPlan(planId, spec, currentState);
      if (plan.integrityHash !== submittedHash) {
        res.status(409).json({ error: "Terraform plan integrity check failed. Re-plan before applying." });
        return;
      }

      const result = applyTerraformPlan(plan);
      auditLog.record("apply", req.auth?.actor ?? "unknown", { kind: "terraform", steps: result.steps.length }, planId);
      logger.info({ planId, steps: result.steps.length }, "Terraform apply executed");

      res.status(200).json({ result });
    } catch (error) {
      next(error);
    }
  });

  router.post("/deploy/detect", requireRole("viewer"), (req, res, next) => {
    try {
      const request = deploymentRequestSchema.parse(req.body);
      const framework = detectFramework(request);
      res.status(200).json({ framework });
    } catch (error) {
      next(error);
    }
  });

  router.post("/deploy", requireRole("admin"), async (req, res, next) => {
    try {
      const request = deploymentRequestSchema.parse(req.body);
      const result = await runDeploymentPipeline(request);

      logger.info(
        { deploymentId: result.deploymentId, framework: result.framework.framework, succeeded: result.succeeded },
        "Deployment pipeline completed"
      );

      res.status(result.succeeded ? 200 : 207).json({ result });
    } catch (error) {
      next(error);
    }
  });

  router.post("/diagnose", requireRole("viewer"), (req, res, next) => {
    try {
      const project = diagnosisRequestSchema.parse(req.body);
      const report = analyzeProject(project);

      auditLog.record(
        "discover",
        req.auth?.actor ?? "unknown",
        { kind: "diagnose", issues: report.summary.total, healthScore: report.summary.healthScore },
        report.diagnosisId
      );
      logger.info(
        { diagnosisId: report.diagnosisId, issues: report.summary.total, healthScore: report.summary.healthScore },
        "Project diagnosis completed"
      );

      res.status(200).json({ report: redactSensitiveValues(report) });
    } catch (error) {
      next(error);
    }
  });

  router.post("/diagnose/fix", requireRole("operator"), (req, res, next) => {
    try {
      const parsed = diagnosisFixRequestSchema.parse(req.body);
      const result = applyFixes(parsed.project, parsed.issueIds);

      auditLog.record(
        "apply",
        req.auth?.actor ?? "unknown",
        { kind: "diagnose-fix", applied: result.applied.length, residual: result.residualReport.summary.total },
        result.diagnosisId
      );
      logger.info(
        { diagnosisId: result.diagnosisId, applied: result.applied.length, residual: result.residualReport.summary.total },
        "Project auto-fix applied"
      );

      res.status(200).json({ result: redactSensitiveValues(result) });
    } catch (error) {
      next(error);
    }
  });

  router.get("/audit", requireRole("viewer"), (_req, res) => {
    const chain = auditLog.verifyChain();
    res.status(200).json({
      entries: auditLog.list(),
      integrity: chain
    });
  });

  return router;
}
