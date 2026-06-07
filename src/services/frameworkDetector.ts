import { DetectedFramework, DeploymentRequest, FrameworkId } from "../domain/deployment";

interface Signature {
  framework: FrameworkId;
  runtime: DetectedFramework["runtime"];
  defaultPort: number;
  buildCommand?: string;
  startCommand?: string;
  fileMatchers: RegExp[];
  dependencyMatchers?: string[];
}

const SIGNATURES: Signature[] = [
  {
    framework: "nextjs",
    runtime: "node",
    defaultPort: 3000,
    buildCommand: "npm run build",
    startCommand: "npm run start",
    fileMatchers: [/next\.config\.(js|ts|mjs)$/i],
    dependencyMatchers: ["next"]
  },
  {
    framework: "nestjs",
    runtime: "node",
    defaultPort: 3000,
    buildCommand: "npm run build",
    startCommand: "node dist/main.js",
    fileMatchers: [/nest-cli\.json$/i],
    dependencyMatchers: ["@nestjs/core"]
  },
  {
    framework: "express",
    runtime: "node",
    defaultPort: 3000,
    buildCommand: "npm install",
    startCommand: "node server.js",
    fileMatchers: [/server\.(js|ts)$/i, /app\.(js|ts)$/i],
    dependencyMatchers: ["express"]
  },
  {
    framework: "react",
    runtime: "static",
    defaultPort: 80,
    buildCommand: "npm run build",
    fileMatchers: [/vite\.config\.(js|ts)$/i],
    dependencyMatchers: ["react", "vite"]
  },
  {
    framework: "vue",
    runtime: "static",
    defaultPort: 80,
    buildCommand: "npm run build",
    fileMatchers: [/vue\.config\.(js|ts)$/i],
    dependencyMatchers: ["vue"]
  },
  {
    framework: "django",
    runtime: "python",
    defaultPort: 8000,
    buildCommand: "pip install -r requirements.txt",
    startCommand: "gunicorn wsgi:application",
    fileMatchers: [/manage\.py$/i]
  },
  {
    framework: "fastapi",
    runtime: "python",
    defaultPort: 8000,
    buildCommand: "pip install -r requirements.txt",
    startCommand: "uvicorn main:app --host 0.0.0.0",
    fileMatchers: [/main\.py$/i],
    dependencyMatchers: ["fastapi"]
  },
  {
    framework: "flask",
    runtime: "python",
    defaultPort: 5000,
    buildCommand: "pip install -r requirements.txt",
    startCommand: "gunicorn app:app",
    fileMatchers: [/app\.py$/i, /wsgi\.py$/i]
  },
  {
    framework: "go",
    runtime: "go",
    defaultPort: 8080,
    buildCommand: "go build -o app",
    startCommand: "./app",
    fileMatchers: [/go\.mod$/i, /main\.go$/i]
  },
  {
    framework: "static",
    runtime: "static",
    defaultPort: 80,
    fileMatchers: [/index\.html$/i]
  }
];

function collectDependencies(packageJson?: Record<string, unknown>): Set<string> {
  const deps = new Set<string>();
  if (!packageJson) return deps;
  for (const field of ["dependencies", "devDependencies"]) {
    const section = packageJson[field];
    if (section && typeof section === "object") {
      for (const name of Object.keys(section as Record<string, unknown>)) {
        deps.add(name);
      }
    }
  }
  return deps;
}

/**
 * Detects the most likely framework from project file paths and (optionally)
 * package.json dependencies. Deterministic and side-effect free.
 */
export function detectFramework(request: DeploymentRequest): DetectedFramework {
  const files = request.files.map((f) => f.toLowerCase());
  const deps = collectDependencies(request.packageJson);

  let best: { signature: Signature; score: number } | undefined;

  for (const signature of SIGNATURES) {
    let score = 0;

    for (const matcher of signature.fileMatchers) {
      if (files.some((file) => matcher.test(file))) {
        score += 2;
      }
    }

    for (const dep of signature.dependencyMatchers ?? []) {
      if (deps.has(dep)) {
        score += 3;
      }
    }

    if (score > 0 && (!best || score > best.score)) {
      best = { signature, score };
    }
  }

  if (!best) {
    return {
      framework: "unknown",
      runtime: "docker",
      defaultPort: 8080,
      confidence: 10
    };
  }

  const maxPossible = best.signature.fileMatchers.length * 2 + (best.signature.dependencyMatchers?.length ?? 0) * 3;
  const confidence = Math.min(99, Math.round((best.score / Math.max(1, maxPossible)) * 100));

  return {
    framework: best.signature.framework,
    runtime: best.signature.runtime,
    buildCommand: best.signature.buildCommand,
    startCommand: best.signature.startCommand,
    defaultPort: best.signature.defaultPort,
    confidence
  };
}
