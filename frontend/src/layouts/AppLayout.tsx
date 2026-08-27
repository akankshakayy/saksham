import { NavLink, Outlet } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import { getHealth } from "../services/api";
import "../styles/layout.css";

export function AppLayout() {
  const { data: health } = useApi(() => getHealth(), []);

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-brand">SAKSHAM</div>
          <div className="sidebar-subtitle">
            Verification Worker
          </div>
        </div>
        <nav className="sidebar-nav" aria-label="Main navigation">
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/applications">
            Applications
          </NavLink>
          <NavLink to="/applications/new">
            New Application
          </NavLink>
        </nav>
        <div className="sidebar-footer">
          <div className="status-indicator">
            <span
              className={`status-dot ${health?.status === "ok" ? "ok" : ""}`}
              aria-label={health?.status === "ok" ? "API connected" : "API unavailable"}
            />
            <span>
              {health?.status === "ok" ? `API v${health.version}` : "API unavailable"}
            </span>
          </div>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
