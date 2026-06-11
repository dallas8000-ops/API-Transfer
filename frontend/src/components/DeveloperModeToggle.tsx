import { useDemoMode } from "../DemoModeContext";

export function DeveloperModeToggle() {
  const { demoMode, pathLockedDemo, allowToggle, setDesignMode } = useDemoMode();

  if (!allowToggle) return null;

  return (
    <label className="mode-toggle" title="Switch between live provider APIs and safe design/demo simulation">
      <span className="muted small">Mode</span>
      <select
        value={demoMode ? "design" : "live"}
        disabled={pathLockedDemo}
        onChange={(e) => setDesignMode(e.target.value === "design")}
      >
        <option value="live">Live</option>
        <option value="design">Design</option>
      </select>
      {pathLockedDemo && <span className="muted small">(demo link)</span>}
    </label>
  );
}
