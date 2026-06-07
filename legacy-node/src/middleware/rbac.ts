import { Request, Response, NextFunction } from "express";
import { env } from "../config/env";

export type Role = "admin" | "operator" | "viewer";

const ROLE_RANK: Record<Role, number> = {
  viewer: 1,
  operator: 2,
  admin: 3
};

function parseKeys(raw: string): Set<string> {
  return new Set(
    raw
      .split(",")
      .map((k) => k.trim())
      .filter((k) => k.length > 0)
  );
}

const adminKeys = parseKeys(env.RBAC_ADMIN_KEYS);
const operatorKeys = parseKeys(env.RBAC_OPERATOR_KEYS);
const viewerKeys = parseKeys(env.RBAC_VIEWER_KEYS);

const rbacConfigured = adminKeys.size > 0 || operatorKeys.size > 0 || viewerKeys.size > 0;

function resolveRole(apiKey: string): Role | undefined {
  if (adminKeys.has(apiKey)) return "admin";
  if (operatorKeys.has(apiKey)) return "operator";
  if (viewerKeys.has(apiKey)) return "viewer";
  return undefined;
}

export interface AuthContext {
  role: Role;
  actor: string;
}

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      auth?: AuthContext;
    }
  }
}

/**
 * Role-based access control. Requires an `x-api-key` header mapped to a role.
 * When no RBAC keys are configured (local dev), requests default to admin so
 * the service remains usable, but a warning posture is assumed in production.
 */
export function requireRole(minimum: Role) {
  return (req: Request, res: Response, next: NextFunction): void => {
    if (!rbacConfigured) {
      if (env.NODE_ENV === "production") {
        res.status(503).json({ error: "RBAC is not configured. Set RBAC_*_KEYS before serving production traffic." });
        return;
      }
      req.auth = { role: "admin", actor: "local-dev" };
      next();
      return;
    }

    const apiKey = req.header("x-api-key")?.trim();
    if (!apiKey) {
      res.status(401).json({ error: "Missing x-api-key header" });
      return;
    }

    const role = resolveRole(apiKey);
    if (!role) {
      res.status(403).json({ error: "Invalid API key" });
      return;
    }

    if (ROLE_RANK[role] < ROLE_RANK[minimum]) {
      res.status(403).json({ error: `Insufficient role. Requires '${minimum}' or higher.` });
      return;
    }

    req.auth = { role, actor: `${role}:${apiKey.slice(0, 4)}***` };
    next();
  };
}
