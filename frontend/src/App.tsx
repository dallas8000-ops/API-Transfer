import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { DeveloperModeToggle } from "./components/DeveloperModeToggle";
import { DemoModeProvider, useDemoMode } from "./DemoModeContext";
import { toDemoPath, toProductionPath } from "./demoMode";
import { BillingSuccess } from "./pages/BillingSuccess";
import { Console } from "./pages/Console";
import { Pricing } from "./pages/Pricing";

function Shell() {
  const location = useLocation();
  const { demoMode, pathLockedDemo } = useDemoMode();

  return (
    <div className="app">
      {demoMode && (
        <div className="notice demo-banner">
          {pathLockedDemo ? (
            <>
              Demo link — design mode only. No live provider changes.{" "}
              <NavLink to={toProductionPath(location.pathname)}>Open live console</NavLink>
            </>
          ) : (
            <>Design mode — safe simulation. Switch to Live in the header to use real providers.</>
          )}
        </div>
      )}
      <header className="topbar">
        <NavLink to="/pricing" className="brand">
          <span className="brand-mark" aria-hidden>
            AT
          </span>
          <span>API Transfer</span>
        </NavLink>
        <nav className="topnav">
          <NavLink to="/pricing" className={({ isActive }) => (isActive ? "active" : "")}>
            Pricing
          </NavLink>
          <NavLink to="/console" className={({ isActive }) => (isActive ? "active" : "")}>
            Console
          </NavLink>
          <DeveloperModeToggle />
          {!demoMode && (
            <NavLink to={toDemoPath("/console")} className="btn btn-outline btn-sm">
              Share demo link
            </NavLink>
          )}
          <a className="btn btn-primary btn-sm" href="/pricing">
            Get started
          </a>
        </nav>
      </header>

      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/pricing" replace />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/console" element={<Console />} />
          <Route path="/demo" element={<Navigate to="/demo/pricing" replace />} />
          <Route path="/demo/pricing" element={<Pricing />} />
          <Route path="/demo/console" element={<Console />} />
          <Route path="/billing/success" element={<BillingSuccess />} />
          <Route path="/demo/billing/success" element={<BillingSuccess />} />
          <Route path="*" element={<Navigate to="/pricing" replace />} />
        </Routes>
      </main>

      <footer className="footer">
        <span>Copyright {new Date().getFullYear()} API Transfer</span>
        <span className="muted">Secure migrations | One-click deploys | AES-256-GCM vault</span>
      </footer>
    </div>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <DemoModeProvider>
        <Shell />
      </DemoModeProvider>
    </BrowserRouter>
  );
}
