import { useDemoMode } from "../DemoModeContext";

export function DeveloperModeToggle() {
  const { demoMode, pathLockedDemo, allowToggle, setDesignMode } = useDemoMode();

  if (!allowToggle) return null;

  return (
    <label className="mode-toggle" title="Live = real Railway/Render APIs. Design = safe simulation.">
      <span className="mode-toggle-label">Mode</span>
      <select
        value={demoMode ? "design" : "live"}
        disabled={pathLockedDemo}
        onChange={(e) => setDesignMode(e.target.value === "design")}
        aria-label="Live or design mode"
      >
        <option value="live">Live</option>
        <option value="design">Design</option>
      </select>
    </label>
  );
}
