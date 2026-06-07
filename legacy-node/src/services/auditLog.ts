import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { env } from "../config/env";
import { integrityHash } from "../security/integrity";
import { redactSensitiveValues } from "../security/redaction";

export type AuditAction = "plan" | "apply" | "rollback" | "verify" | "discover";

export interface AuditEntry {
  id: string;
  action: AuditAction;
  actor: string;
  planId?: string;
  details: unknown;
  timestamp: string;
  previousHash: string;
  entryHash: string;
}

const GENESIS_HASH = "0".repeat(64);

class AuditLog {
  private readonly entries: AuditEntry[] = [];
  private readonly filePath = env.AUDIT_LOG_PATH;

  constructor() {
    this.load();
  }

  private load(): void {
    if (!existsSync(this.filePath)) {
      return;
    }
    try {
      const raw = readFileSync(this.filePath, "utf8");
      const parsed = JSON.parse(raw) as AuditEntry[];
      if (Array.isArray(parsed)) {
        this.entries.push(...parsed);
      }
    } catch {
      // Corrupt or unreadable log: start fresh in memory but do not crash.
    }
  }

  private persist(): void {
    const dir = dirname(this.filePath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
    writeFileSync(this.filePath, JSON.stringify(this.entries, null, 2), "utf8");
  }

  record(action: AuditAction, actor: string, details: unknown, planId?: string): AuditEntry {
    const previousHash = this.entries.at(-1)?.entryHash ?? GENESIS_HASH;
    const safeDetails = redactSensitiveValues(details);
    const timestamp = new Date().toISOString();
    const id = randomUUID();

    const entryHash = integrityHash({ id, action, actor, planId, details: safeDetails, timestamp, previousHash });

    const entry: AuditEntry = {
      id,
      action,
      actor,
      planId,
      details: safeDetails,
      timestamp,
      previousHash,
      entryHash
    };

    this.entries.push(entry);
    this.persist();
    return entry;
  }

  list(): AuditEntry[] {
    return [...this.entries];
  }

  verifyChain(): { valid: boolean; brokenAt?: string } {
    let previousHash = GENESIS_HASH;

    for (const entry of this.entries) {
      const expected = integrityHash({
        id: entry.id,
        action: entry.action,
        actor: entry.actor,
        planId: entry.planId,
        details: entry.details,
        timestamp: entry.timestamp,
        previousHash
      });

      if (entry.previousHash !== previousHash || entry.entryHash !== expected) {
        return { valid: false, brokenAt: entry.id };
      }

      previousHash = entry.entryHash;
    }

    return { valid: true };
  }
}

export const auditLog = new AuditLog();
