import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { listDashboard } from "../api/client";
import { useNow } from "../hooks/useNow";
import type { DashboardItem, Status, Severity } from "../types";
import SeverityBadge from "../components/SeverityBadge";
import SlaCountdown from "../components/SlaCountdown";
import StatusChip from "../components/StatusChip";
import Spinner from "../components/Spinner";

const STATUSES: Status[] = ["OPEN", "ACK", "ESCALATED", "RESOLVED"];
const LS_KEY = "ticketresolve_assignee";

/** Debounce delay (ms) before committing assignee to fetch + localStorage */
const ASSIGNEE_DEBOUNCE_MS = 350;

const SEVERITY_FILTERS: { value: Severity; label: string; sla: string }[] = [
  { value: "P0", label: "Crítico", sla: "SLA 15 min" },
  { value: "P1", label: "Alto",    sla: "SLA 4 h" },
  { value: "P2", label: "Normal",  sla: "SLA 24 h" },
];

/** SLA window (ms) under which a countdown is considered "about to breach". */
const SLA_AT_RISK_MS = 15 * 60 * 1000;

// ── Sub-components ──────────────────────────────────────────────

function initialsOf(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "—";
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function AssigneeAvatar({ name }: { name: string }) {
  return (
    <span className="assignee-avatar" aria-hidden="true">
      {initialsOf(name)}
    </span>
  );
}

/** Shimmer skeleton for the initial loading state. */
function SkeletonTable() {
  return (
    <table className="skeleton-table" aria-hidden="true">
      <tbody>
        {Array.from({ length: 5 }).map((_, i) => (
          <tr key={i} className="skeleton-row">
            <td style={{ paddingLeft: "var(--space-6)" }}>
              <div className="skeleton-cell w-20" />
            </td>
            <td><div className="skeleton-cell w-30" /></td>
            <td><div className="skeleton-cell w-30" /></td>
            <td><div className="skeleton-cell w-40" /></td>
            <td><div className="skeleton-cell w-60" /></td>
            <td><div className="skeleton-cell w-20" /></td>
            <td><div className="skeleton-cell w-40" /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Dashboard ───────────────────────────────────────────────────

export default function Dashboard() {
  /**
   * assigneeInput  — controlled value, updates on every keystroke (UI stays
   *                  responsive).
   * assigneeQuery  — debounced value that actually drives fetch + localStorage.
   *                  (REC-06 debounce; IMP-06 race guard)
   */
  const [assigneeInput, setAssigneeInput] = useState<string>(
    () => localStorage.getItem(LS_KEY) ?? ""
  );
  const [assigneeQuery, setAssigneeQuery] = useState<string>(
    () => localStorage.getItem(LS_KEY) ?? ""
  );
  const [status, setStatus] = useState<Status>("OPEN");
  const [items, setItems] = useState<DashboardItem[]>([]);
  const [severityFilter, setSeverityFilter] = useState<Severity | null>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);

  // ── Debounce assignee input (REC-06) ──────────────────────────
  useEffect(() => {
    const timer = setTimeout(() => {
      const trimmed = assigneeInput.trim();
      setAssigneeQuery(trimmed);
      localStorage.setItem(LS_KEY, assigneeInput);
    }, ASSIGNEE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [assigneeInput]);

  // ── Single fetch with AbortController (IMP-06) ────────────────
  /**
   * Whether the current view is "all pending" mode (no engineer filter).
   * True when assigneeQuery is empty/whitespace — the backend returns every
   * ticket in the selected state regardless of assignee.
   */
  const isAllMode = assigneeQuery.trim() === "";

  /**
   * fetchTickets — consolidated fetch function.
   * `isInitial` drives isLoading vs isRefreshing so the table skeleton only
   * shows on first load (not on filter changes when rows are already visible).
   * Empty `query` is valid: it triggers the "all pending" view.
   */
  const fetchTickets = useCallback(
    async (query: string, st: Status, isInitial: boolean, signal: AbortSignal) => {
      if (isInitial) {
        setIsLoading(true);
        setItems([]);
      } else {
        setIsRefreshing(true);
      }
      setError(null);

      try {
        // listDashboard omits the assignee param when query is empty,
        // causing the backend to return ALL tickets for that status.
        const data = await listDashboard(query, st, signal);

        // If this request was aborted (stale response), ignore it (IMP-06)
        if (signal.aborted) return;

        setItems(data);
        setLastFetched(new Date());
      } catch (err) {
        if (signal.aborted) return; // expected cancellation — not an error
        setError(err instanceof Error ? err.message : "Error al cargar tickets");
      } finally {
        if (!signal.aborted) {
          setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    },
    []
  );

  /**
   * Main effect — fires when assigneeQuery or status changes.
   * Creates a new AbortController; cancels the previous one via cleanup.
   * Empty assigneeQuery now triggers a fetch for ALL tickets (all-mode).
   */
  useEffect(() => {
    const controller = new AbortController();
    const isInitial = items.length === 0 && !error;

    void fetchTickets(assigneeQuery, status, isInitial, controller.signal);

    return () => {
      controller.abort();
    };
    // items.length and error are intentionally excluded — they are not
    // parameters for "when to re-fetch", only assigneeQuery/status are.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assigneeQuery, status, fetchTickets]);

  // ── Polling every 30 s (refresh, not initial load) ────────────
  // Uses a ref to always call with the latest query/status without
  // re-registering the interval when those values change.
  const queryRef = useRef(assigneeQuery);
  const statusRef = useRef(status);
  queryRef.current = assigneeQuery;
  statusRef.current = status;

  useEffect(() => {
    const id = setInterval(() => {
      const controller = new AbortController();
      void fetchTickets(queryRef.current, statusRef.current, false, controller.signal);
      // The interval itself is cleared on unmount; individual poll requests
      // are fire-and-forget (the component won't unmount mid-poll in practice).
    }, 30_000);

    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchTickets]);

  // ── Manual refresh (button) ───────────────────────────────────
  const refreshControllerRef = useRef<AbortController | null>(null);

  function handleManualRefresh() {
    if (isLoading || isRefreshing) return;
    refreshControllerRef.current?.abort();
    const controller = new AbortController();
    refreshControllerRef.current = controller;
    void fetchTickets(assigneeQuery, status, false, controller.signal);
  }

  // ── Assignee input handler (UI layer — no fetch, no LS write) ──
  function handleAssigneeChange(value: string) {
    setAssigneeInput(value);
    // Debounce effect handles localStorage + query update (REC-06)
  }

  function toggleSeverityFilter(sev: Severity) {
    setSeverityFilter((current) => (current === sev ? null : sev));
  }

  const now = useNow();
  const navigate = useNavigate();

  function goToTicket(ticketId: string) {
    navigate(`/ticket/${encodeURIComponent(ticketId)}`);
  }

  function handleRowKeyDown(e: React.KeyboardEvent<HTMLTableRowElement>, ticketId: string) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      goToTicket(ticketId);
    }
  }

  const total = items.length;
  const countBySev = (sev: Severity) =>
    items.filter((i) => i.severity === sev).length;
  const p0 = countBySev("P0");
  const p1 = countBySev("P1");
  const p2 = countBySev("P2");

  // Distribution shares for the mini stacked bar in the "total" card.
  const dist = useMemo(() => {
    if (total === 0) return { p0: 0, p1: 0, p2: 0 };
    return {
      p0: Math.round((p0 / total) * 1000) / 10,
      p1: Math.round((p1 / total) * 1000) / 10,
      p2: Math.round((p2 / total) * 1000) / 10,
    };
  }, [total, p0, p1, p2]);

  // Tickets whose SLA deadline has already passed — "command center" alert.
  const breachedCount = useMemo(
    () => items.filter((i) => new Date(i.sla_deadline).getTime() - now <= 0).length,
    [items, now]
  );

  // Client-side severity filter — purely presentational, keeps backend SLA order.
  const visibleItems = useMemo(
    () => (severityFilter ? items.filter((i) => i.severity === severityFilter) : items),
    [items, severityFilter]
  );

  /** Urgency class for a row, derived from its live SLA remaining time. */
  function rowUrgencyClass(item: DashboardItem): string {
    const remaining = new Date(item.sla_deadline).getTime() - now;
    const classes = [`row-${item.severity.toLowerCase()}`];
    if (remaining <= 0) classes.push("row-sla-breached");
    else if (remaining < SLA_AT_RISK_MS) classes.push("row-sla-at-risk");
    return classes.join(" ");
  }

  return (
    <div className="dashboard-layout" aria-label="Dashboard de incidentes">

      {/* ── Header ─────────────────────────────────────────── */}
      <header className="dashboard-header">
        <div className="dashboard-title-group">
          <span className="dashboard-eyebrow">
            <span className="dashboard-eyebrow-dot" aria-hidden="true" />
            Centro de Operaciones
          </span>
          <h1 className="dashboard-title">Dashboard del Ingeniero</h1>
          <p className="dashboard-subtitle">
            {assigneeInput.trim() ? (
              <>
                Turno activo de <strong>{assigneeInput.trim()}</strong> · monitoreo de
                incidentes en vivo, priorizados por vencimiento de SLA.
              </>
            ) : (
              <>
                Mostrando <strong>todos los pendientes</strong> del sistema · deja el nombre
                vacío para ver la vista global, o escribe un ingeniero para filtrar su cola.
              </>
            )}
          </p>
        </div>

        {breachedCount > 0 && (
          <div className="dashboard-alert-pill" role="status" aria-live="polite">
            <span className="dashboard-alert-pill-icon" aria-hidden="true">⚠</span>
            <span>
              <strong>{breachedCount}</strong> ticket{breachedCount !== 1 ? "s" : ""} con SLA vencido
            </span>
          </div>
        )}
      </header>

      {/* ── Stat cards ─────────────────────────────────────── */}
      <section className="stat-cards" aria-label="Resumen de tickets — clic en una severidad para filtrar la tabla">
        <div
          className="stat-card stat-total"
          aria-label={`Total: ${total} tickets`}
        >
          <div className="stat-card-label">Total tickets</div>
          <div className="stat-card-value">{total}</div>
          <div className="stat-card-sub">
            {assigneeInput.trim() ? `${assigneeInput.trim()} · ${status}` : `Todos · ${status}`}
          </div>

          {total > 0 && (
            <div className="stat-distribution" aria-hidden="true">
              {dist.p0 > 0 && (
                <span className="stat-distribution-seg seg-p0" style={{ width: `${dist.p0}%` }} />
              )}
              {dist.p1 > 0 && (
                <span className="stat-distribution-seg seg-p1" style={{ width: `${dist.p1}%` }} />
              )}
              {dist.p2 > 0 && (
                <span className="stat-distribution-seg seg-p2" style={{ width: `${dist.p2}%` }} />
              )}
            </div>
          )}

          <div className="stat-card-bar" aria-hidden="true" />
        </div>

        {SEVERITY_FILTERS.map(({ value, label, sla }) => {
          const count = value === "P0" ? p0 : value === "P1" ? p1 : p2;
          const isActive = severityFilter === value;
          const isCritical = value === "P0" && count > 0;
          return (
            <button
              key={value}
              type="button"
              className={`stat-card stat-${value.toLowerCase()}${isCritical ? " has-incidents" : ""}${isActive ? " is-active-filter" : ""}`}
              aria-label={`${value} ${label}: ${count} tickets — clic para ${isActive ? "quitar filtro" : "filtrar por esta severidad"}`}
              aria-pressed={isActive}
              onClick={() => toggleSeverityFilter(value)}
              disabled={total === 0}
            >
              <div className="stat-card-label">{value} · {label}</div>
              <div className="stat-card-value">{count}</div>
              <div className="stat-card-sub">{sla}</div>
              <div className="stat-card-bar" aria-hidden="true" />
              {isActive && (
                <span className="stat-card-filter-tag" aria-hidden="true">Filtrando</span>
              )}
            </button>
          );
        })}
      </section>

      {/* ── Controls ───────────────────────────────────────── */}
      <div
        className="filter-row"
        role="search"
        aria-label="Filtros de búsqueda"
      >
        <div className="field inline field-assignee">
          <div className="field-inline-head">
            <label htmlFor="assignee-input">Ingeniero asignado</label>
            <span id="assignee-search-hint" className="composer-hint">
              Deja vacío para ver todos los pendientes · persistido en sesión
            </span>
          </div>
          <div className="assignee-input-wrap">
            <span className="assignee-preview-avatar" aria-hidden="true">
              {initialsOf(assigneeInput)}
            </span>
            <input
              id="assignee-input"
              type="text"
              value={assigneeInput}
              onChange={(e) => handleAssigneeChange(e.target.value)}
              placeholder="Buscar por nombre del ingeniero…"
              aria-describedby="assignee-search-hint"
              autoComplete="off"
            />
            <svg
              className="assignee-search-icon"
              aria-hidden="true"
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
            >
              <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.6" />
              <path d="M11 11L14.5 14.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </div>
        </div>

        <div className="field inline field-status">
          <div className="field-inline-head">
            <span className="composer-field-label" id="status-group-label">Estado</span>
          </div>
          <div
            className="status-segmented"
            role="radiogroup"
            aria-labelledby="status-group-label"
          >
            {STATUSES.map((s) => {
              const checked = status === s;
              return (
                <button
                  key={s}
                  type="button"
                  role="radio"
                  aria-checked={checked}
                  className={`status-segment status-segment-${s.toLowerCase()}${checked ? " is-selected" : ""}`}
                  onClick={() => setStatus(s)}
                >
                  {s}
                </button>
              );
            })}
          </div>
        </div>

        <div className="filter-row-actions">
          {severityFilter && (
            <button
              type="button"
              className="severity-filter-tag"
              onClick={() => setSeverityFilter(null)}
              aria-label={`Quitar filtro de severidad ${severityFilter}`}
            >
              <SeverityBadge severity={severityFilter} />
              <span aria-hidden="true">✕</span>
            </button>
          )}

          {lastFetched && (
            <span
              className="last-updated-label"
              aria-live="polite"
              aria-atomic="true"
            >
              {isRefreshing ? (
                <>
                  <Spinner size={10} />
                  Actualizando…
                </>
              ) : (
                <>
                  Actualizado:{" "}
                  {lastFetched.toLocaleTimeString("es-GT", {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </>
              )}
            </span>
          )}
          <button
            onClick={handleManualRefresh}
            disabled={isLoading || isRefreshing}
            className="btn-refresh"
            aria-label="Refrescar datos del dashboard"
            aria-busy={isRefreshing}
          >
            {isRefreshing ? (
              <>
                <Spinner size={12} />
                Actualizando…
              </>
            ) : (
              <>↻ Refrescar</>
            )}
          </button>
        </div>
      </div>

      {/* ── State: initial loading — skeleton rows ──────────── */}
      {isLoading && items.length === 0 && (
        <div
          className="table-panel"
          role="status"
          aria-label="Cargando tickets"
          aria-live="polite"
        >
          <div className="table-panel-header">
            <span className="table-panel-title">Cargando…</span>
          </div>
          <div className="table-wrapper">
            <SkeletonTable />
          </div>
        </div>
      )}

      {/* ── State: error ───────────────────────────────────── */}
      {error && (
        <div className="msg msg-error" role="alert" aria-live="assertive">
          <span className="msg-icon" aria-hidden="true">⚠</span>
          <div>
            <strong>Error al cargar</strong>
            <div style={{ marginTop: "var(--space-1)" }}>{error}</div>
          </div>
        </div>
      )}

      {/* ── State: empty results ───────────────────────────── */}
      {!isLoading && !error && items.length === 0 && (
        <div className="state-container" role="status" aria-live="polite">
          <span className="state-icon" aria-hidden="true">◫</span>
          <p className="state-title">Sin tickets pendientes</p>
          <p className="state-subtitle">
            {isAllMode ? (
              <>
                No hay tickets con estado <strong>{status}</strong> en el sistema.
              </>
            ) : (
              <>
                No hay tickets con estado <strong>{status}</strong> para{" "}
                <strong>{assigneeInput.trim()}</strong>.
              </>
            )}
          </p>
        </div>
      )}

      {/* ── Table ──────────────────────────────────────────── */}
      {items.length > 0 && (
        <div
          className="table-panel"
          role="region"
          aria-label={isAllMode ? "Todos los tickets pendientes" : `Tickets de ${assigneeInput}`}
          aria-busy={isRefreshing}
        >
          <div className="table-panel-header">
            <span className="table-panel-title">
              {visibleItems.length} de {total} ticket{total !== 1 ? "s" : ""}
              <span className="table-panel-status-pill">{status}</span>
              {severityFilter && (
                <span className="table-panel-filter-pill">
                  filtrado · {severityFilter}
                </span>
              )}
            </span>
            <span className="table-panel-meta">
              {isRefreshing ? (
                <span className="table-panel-meta-busy">
                  <Spinner size={10} />
                  Actualizando…
                </span>
              ) : isAllMode ? (
                "Vista global · todos los ingenieros · SLA ascendente"
              ) : (
                "Ordenado por SLA ascendente"
              )}
            </span>
          </div>

          <div className="table-wrapper">
            {visibleItems.length === 0 ? (
              <div className="state-container state-container-inline" role="status" aria-live="polite">
                <span className="state-icon" aria-hidden="true">◫</span>
                <p className="state-title">Ningún ticket {severityFilter} en esta vista</p>
                <p className="state-subtitle">
                  Tu cola tiene {total} ticket{total !== 1 ? "s" : ""} con estado{" "}
                  <strong>{status}</strong>, pero ninguno con severidad{" "}
                  <strong>{severityFilter}</strong>.
                </p>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setSeverityFilter(null)}
                >
                  Mostrar todas las severidades
                </button>
              </div>
            ) : (
              <table aria-label="Tabla de tickets">
                <thead>
                  <tr>
                    <th scope="col">ID</th>
                    <th scope="col">Severidad</th>
                    <th scope="col">Estado</th>
                    <th scope="col" aria-sort="ascending">SLA restante</th>
                    <th scope="col">Título</th>
                    <th scope="col">Servicio</th>
                    <th scope="col">Asignado</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleItems.map((item) => (
                    <tr
                      key={item.ticket_id}
                      className={`row-clickable ${rowUrgencyClass(item)}`}
                      role="link"
                      tabIndex={0}
                      aria-label={`Abrir ticket ${item.ticket_id} — ${item.title}`}
                      onClick={() => goToTicket(item.ticket_id)}
                      onKeyDown={(e) => handleRowKeyDown(e, item.ticket_id)}
                    >
                      <td>
                        <span className="ticket-id">{item.ticket_id}</span>
                      </td>
                      <td>
                        <SeverityBadge severity={item.severity} />
                      </td>
                      <td>
                        <StatusChip status={item.status} />
                      </td>
                      <td>
                        <SlaCountdown deadline={item.sla_deadline} />
                      </td>
                      <td>
                        <span className="ticket-title" title={item.title}>
                          {item.title}
                        </span>
                      </td>
                      <td>
                        <span className="ticket-service">{item.service}</span>
                      </td>
                      <td>
                        <div className="ticket-assignee">
                          <AssigneeAvatar name={item.assignee} />
                          <span className="assignee-name">{item.assignee}</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
