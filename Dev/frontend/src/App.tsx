import { NavLink, Outlet } from "react-router-dom";
import "./styles.css";

export default function App() {
  return (
    <>
      <nav className="nav" role="navigation" aria-label="Navegación principal">
        <NavLink to="/nuevo" className="nav-brand" aria-label="TicketResolve — inicio">
          <span className="nav-brand-logo" aria-hidden="true">TR</span>
          <span>TicketResolve</span>
        </NavLink>

        <span className="nav-separator" aria-hidden="true" />

        <div className="nav-links">
          <NavLink
            to="/nuevo"
            className={({ isActive }) => (isActive ? "active" : "")}
          >
            Nuevo Ticket
          </NavLink>
          <NavLink
            to="/dashboard"
            className={({ isActive }) => (isActive ? "active" : "")}
          >
            Dashboard
          </NavLink>
        </div>

        <span className="nav-spacer" aria-hidden="true" />

        <div className="nav-status" aria-label="Estado del sistema: operativo">
          <span className="nav-status-dot" aria-hidden="true" />
          <span>Sistema operativo</span>
        </div>
      </nav>

      <main className="page-container">
        <Outlet />
      </main>
    </>
  );
}
