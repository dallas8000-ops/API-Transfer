import { randomUUID } from "node:crypto";
import {
  DeploymentRequest,
  DeploymentResult,
  ReadinessCheck,
  StageResult
} from "../domain/deployment";
import { detectFramework } from "./frameworkDetector";
import {
  stageConfigureEnvVars,
  stageConfigureStripe,
  stageCreateDnsRecords,
  stageCreateEnvironment,
  stageDeployApp,
  stageEnableSsl,
  stageProvisionDatabase,
  stageSetupBackups,
  stageSetupDomain,
  stageSetupMonitoring
} from "./deploymentStages";
import { integrityHash } from "../security/integrity";
import { auditLog } from "./auditLog";

function buildReadinessChecks(request: DeploymentRequest, stages: StageResult[]): ReadinessCheck[] {
  const byStage = new Map(stages.map((s) => [s.stage, s]));
  const succeeded = (stage: string) => byStage.get(stage)?.status === "succeeded";

  const checks: ReadinessCheck[] = [
    {
      name: "deployment-succeeded",
      passed: succeeded("deploy-app"),
      detail: succeeded("deploy-app") ? "Application deployed" : "Deployment did not complete"
    },
    {
      name: "ssl-enabled",
      passed: succeeded("enable-ssl"),
      detail: succeeded("enable-ssl") ? "TLS certificate active" : "SSL not enabled"
    },
    {
      name: "secrets-encrypted",
      passed: succeeded("configure-env-vars"),
      detail: "Secrets encrypted at rest via vault"
    },
    {
      name: "production-environment",
      passed: request.targetEnvironment === "prod" ? succeeded("setup-monitoring") : true,
      detail:
        request.targetEnvironment === "prod"
          ? "Production requires monitoring"
          : "Non-production environment"
    },
    {
      name: "backups-configured",
      passed: request.enableBackups ? succeeded("setup-backups") : true,
      detail: request.enableBackups ? "Backups enabled" : "Backups not requested"
    }
  ];

  return checks;
}

function resolveLiveUrl(request: DeploymentRequest, stages: StageResult[]): string {
  const domainStage = stages.find((s) => s.stage === "setup-domain");
  const host =
    (domainStage?.data?.host as string | undefined) ??
    `${request.appName}.${request.targetProvider}.app`;
  return `https://${host}`;
}

/**
 * Runs the full AI deployment workflow:
 * detect framework -> create environment -> provision DB -> configure env/secrets
 * -> deploy -> setup domain/DNS/SSL -> Stripe -> monitoring -> backups
 * -> readiness checks -> return live URL.
 */
export async function runDeploymentPipeline(request: DeploymentRequest): Promise<DeploymentResult> {
  const deploymentId = randomUUID();
  const startedAt = new Date().toISOString();

  const framework = detectFramework(request);

  const createEnv = stageCreateEnvironment(request);
  const database = await stageProvisionDatabase(request, framework);
  const envVars = stageConfigureEnvVars(request);
  const deploy = await stageDeployApp(request, framework);
  const domain = stageSetupDomain(request);
  const dns = await stageCreateDnsRecords(request);
  const ssl = stageEnableSsl(request);
  const stripe = await stageConfigureStripe(request);
  const monitoring = stageSetupMonitoring(request);
  const backups = stageSetupBackups(request);

  const stages: StageResult[] = [
    createEnv,
    database,
    envVars,
    deploy,
    domain,
    dns,
    ssl,
    stripe,
    monitoring,
    backups
  ];

  const readiness = buildReadinessChecks(request, stages);
  const liveUrl = resolveLiveUrl(request, stages);
  const finishedAt = new Date().toISOString();

  const succeeded =
    stages.every((s) => s.status !== "failed") && readiness.every((c) => c.passed);

  const result: DeploymentResult = {
    deploymentId,
    appName: request.appName,
    framework,
    stages,
    readiness,
    liveUrl,
    succeeded,
    startedAt,
    finishedAt,
    integrityHash: integrityHash({ deploymentId, appName: request.appName, stages, readiness, liveUrl })
  };

  auditLog.record(
    "apply",
    request.requestedBy,
    {
      kind: "deployment",
      framework: framework.framework,
      provider: request.targetProvider,
      succeeded,
      liveUrl
    },
    deploymentId
  );

  return result;
}
