import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import {
  canUseDeveloperDemoToggle,
  getDeveloperDemoOverride,
  isDemoPath,
  setAllowDemoToggle,
  setDeveloperDemoOverride,
} from "./demoMode";

type DemoModeContextValue = {
  demoMode: boolean;
  pathLockedDemo: boolean;
  allowToggle: boolean;
  setDesignMode: (enabled: boolean) => void;
  refreshAllowToggle: (allowed: boolean) => void;
};

const DemoModeContext = createContext<DemoModeContextValue | null>(null);

export function DemoModeProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const pathLockedDemo = isDemoPath(location.pathname);
  const [devDemo, setDevDemo] = useState(getDeveloperDemoOverride);
  const [allowToggle, setAllowToggle] = useState(canUseDeveloperDemoToggle);

  const refreshAllowToggle = useCallback((allowed: boolean) => {
    setAllowDemoToggle(allowed);
    setAllowToggle(allowed);
    if (!allowed) {
      setDeveloperDemoOverride(false);
      setDevDemo(false);
    }
  }, []);

  const setDesignMode = useCallback(
    (enabled: boolean) => {
      if (pathLockedDemo || !canUseDeveloperDemoToggle()) return;
      setDeveloperDemoOverride(enabled);
      setDevDemo(enabled);
    },
    [pathLockedDemo],
  );

  const demoMode = pathLockedDemo || devDemo;

  const value = useMemo(
    () => ({ demoMode, pathLockedDemo, allowToggle, setDesignMode, refreshAllowToggle }),
    [demoMode, pathLockedDemo, allowToggle, setDesignMode, refreshAllowToggle],
  );

  return <DemoModeContext.Provider value={value}>{children}</DemoModeContext.Provider>;
}

export function useDemoMode(): DemoModeContextValue {
  const ctx = useContext(DemoModeContext);
  if (!ctx) {
    throw new Error("useDemoMode must be used within DemoModeProvider");
  }
  return ctx;
}
