import type { ReviewedApp } from "./features/AccountReview";

export function reviewedAppRepoUrl(app: ReviewedApp): string {
  const settings = app.settings;
  const candidates = [settings.repoUrl, settings.gitRepo, settings.repo, settings.sourceRepo];
  for (const value of candidates) {
    if (typeof value !== "string") continue;
    const trimmed = value.trim();
    if (!trimmed) continue;
    if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) return trimmed;
    return `https://github.com/${trimmed.replace(/^\//, "")}`;
  }
  return "";
}

export function reviewedAppBranch(app: ReviewedApp): string {
  const branch = app.settings.branch;
  return typeof branch === "string" ? branch : "";
}
