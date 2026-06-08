import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { BillingSuccess } from "./pages/BillingSuccess";
import { Console } from "./pages/Console";
import { Pricing } from "./pages/Pricing";

function Shell() {
  return (
    <div className="app">
      <header className="topbar">
        <NavLink to="/" className="brand">
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
          <Route path="/billing/success" element={<BillingSuccess />} />
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
      <Shell />
    </BrowserRouter>
  );
}
