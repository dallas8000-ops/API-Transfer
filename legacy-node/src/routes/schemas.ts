import { z } from "zod";

const secretSchema = z.object({
  key: z.string().min(1),
  value: z.string().min(1)
});

const serviceSchema = z.object({
  name: z.string().min(1),
  runtime: z.enum(["node", "python", "go", "docker", "static"]),
  buildCommand: z.string().optional(),
  startCommand: z.string().optional(),
  region: z.string().optional(),
  replicas: z.number().int().positive().optional(),
  environment: z.record(z.string(), z.string()),
  secrets: z.array(secretSchema)
});

const domainSchema = z.object({
  host: z.string().min(1),
  path: z.string().optional(),
  tlsRequired: z.boolean()
});

const dbSchema = z.object({
  name: z.string().min(1),
  engine: z.enum(["postgres", "mysql", "redis"]),
  version: z.string().optional()
});

export const migrationSpecSchema = z.object({
  appName: z.string().min(1),
  sourceProvider: z.enum(["render", "railway", "fly", "kong", "terraform", "supabase"]),
  targetProvider: z.enum(["render", "railway", "fly", "kong", "terraform", "supabase"]),
  services: z.array(serviceSchema),
  domains: z.array(domainSchema),
  databases: z.array(dbSchema),
  metadata: z.object({
    requestedBy: z.string().min(1),
    requestedAt: z.iso.datetime(),
    environment: z.enum(["dev", "stage", "prod"])
  })
});

export const createPlanRequestSchema = z.object({
  spec: migrationSpecSchema
});

export const applyPlanRequestSchema = z.object({
  spec: migrationSpecSchema,
  plan: z.object({
    planId: z.string().min(1),
    summary: z.string(),
    riskScore: z.number(),
    confidence: z.number(),
    steps: z.array(z.string()),
    warnings: z.array(z.string()),
    createdAt: z.string(),
    integrityHash: z.string()
  }),
  approvedBy: z.string().min(3)
});

export const deploymentRequestSchema = z.object({
  appName: z.string().min(1),
  targetProvider: z.enum(["render", "railway", "fly", "kong", "terraform", "supabase"]),
  region: z.string().optional(),
  files: z.array(z.string()).default([]),
  packageJson: z.record(z.string(), z.unknown()).optional(),
  environment: z.record(z.string(), z.string()).default({}),
  secrets: z.array(secretSchema).default([]),
  domain: z.string().optional(),
  enableStripe: z.boolean().default(false),
  enableMonitoring: z.boolean().default(false),
  enableBackups: z.boolean().default(false),
  requestedBy: z.string().min(1),
  targetEnvironment: z.enum(["dev", "stage", "prod"]).default("stage")
});

export const diagnosisRequestSchema = z.object({
  appName: z.string().min(1),
  targetProvider: z.enum(["render", "railway", "fly", "kong", "terraform", "supabase"]),
  files: z.array(z.string()).default([]),
  packageJson: z.record(z.string(), z.unknown()).optional(),
  environment: z.record(z.string(), z.string()).default({}),
  secrets: z.array(secretSchema).default([]),
  domain: z.string().optional(),
  enableStripe: z.boolean().default(false),
  enableMonitoring: z.boolean().default(false),
  enableBackups: z.boolean().default(false),
  targetEnvironment: z.enum(["dev", "stage", "prod"]).default("stage"),
  requestedBy: z.string().min(1)
});

export const diagnosisFixRequestSchema = z.object({
  project: diagnosisRequestSchema,
  /** When omitted, all auto-fixable issues are applied. */
  issueIds: z.array(z.string().min(1)).optional()
});
