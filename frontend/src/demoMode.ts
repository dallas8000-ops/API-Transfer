const DEMO_PREFIX = "/demo";
const DEMO_MODE_KEY = "apitransfer-demo-mode";
const ALLOW_TOGGLE_KEY = "apitransfer-allow-demo-toggle";

export function isDemoPath(pathname = globalThis.location?.pathname || ""): boolean {
  const path = pathname.toLowerCase();
  return path === DEMO_PREFIX || path.startsWith(`${DEMO_PREFIX}/`);
}

export function setAllowDemoToggle(allowed: boolean): void {
  try {
    if (allowed) localStorage.setItem(ALLOW_TOGGLE_KEY, "1");
    else localStorage.removeItem(ALLOW_TOGGLE_KEY);
  } catch {
    /* ignore */
  }
}

export function canUseDeveloperDemoToggle(): boolean {
  try {
    return localStorage.getItem(ALLOW_TOGGLE_KEY) === "1";
  } catch {
    return false;
  }
}

export function getDeveloperDemoOverride(): boolean {
  if (!canUseDeveloperDemoToggle()) return false;
  try {
    return localStorage.getItem(DEMO_MODE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setDeveloperDemoOverride(enabled: boolean): void {
  if (!canUseDeveloperDemoToggle()) return;
  try {
    if (enabled) localStorage.setItem(DEMO_MODE_KEY, "1");
    else localStorage.removeItem(DEMO_MODE_KEY);
  } catch {
    /* ignore */
  }
}

/** True when demo/design mode is active (public demo URL or developer toggle). */
export function isDemoModeActive(pathname = globalThis.location?.pathname || ""): boolean {
  if (isDemoPath(pathname)) return true;
  return getDeveloperDemoOverride();
}

export function toDemoPath(path: string): string {
  if (!path.startsWith("/")) return `${DEMO_PREFIX}/${path}`;
  if (isDemoPath(path)) return path;
  return `${DEMO_PREFIX}${path}`;
}

export function toProductionPath(path: string): string {
  if (!isDemoPath(path)) return path;
  const stripped = path.slice(DEMO_PREFIX.length) || "/";
  return stripped.startsWith("/") ? stripped : `/${stripped}`;
}
