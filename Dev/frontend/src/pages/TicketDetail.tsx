import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { addComment, getTicket, reassignTicket, resolveTicket, updateTicketStatus, VersionConflictError } from "../api/client";
import type { Status } from "../types";
import { useNow } from "../hooks/useNow";
import type { TicketComment, TicketDetail as TicketDetailData, TicketEvent } from "../types";
import SeverityBadge from "../components/SeverityBadge";
import StatusChip from "../components/StatusChip";
import SlaCountdown from "../components/SlaCountdown";
import Spinner from "../components/Spinner";

const LS_ACTOR_KEY = "ticketresolve_actor";

// ── Helpers ──────────────────────────────────────────────────────

function initialsOf(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "—";
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("es-GT", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(bytes?: number): string | null {
  if (bytes === undefined || bytes === null || Number.isNaN(bytes)) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  if (dot < 0 || dot === filename.length - 1) return "FILE";
  return filename.slice(dot + 1).toUpperCase().slice(0, 4);
}

const ATTACHMENT_GLYPHS: Record<string, string> = {
  PNG: "▣", JPG: "▣", JPEG: "▣", GIF: "▣", SVG: "▣", WEBP: "▣",
  PDF: "▤", DOC: "▤", DOCX: "▤", TXT: "▤", MD: "▤",
  LOG: "▥", JSON: "▥", YML: "▥", YAML: "▥", XML: "▥", CSV: "▥",
  ZIP: "▦", TAR: "▦", GZ: "▦", RAR: "▦",
};

function attachmentGlyph(filename: string): string {
  return ATTACHMENT_GLYPHS[extensionOf(filename)] ?? "▢";
}

const EVENT_LABELS: Record<string, string> = {
  CREATED: "Ticket creado",
  ACK: "Reconocido (ACK)",
  ACKNOWLEDGED: "Reconocido (ACK)",
  ESCALATED: "Escalado",
  ASSIGNED: "Reasignado",
  RESOLVED: "Resuelto",
  COMMENT: "Comentario agregado",
  COMMENT_ADDED: "Comentario agregado",
  STATUS_CHANGED: "Cambio de estado",
  ALERT_DUPLICATE: "Alerta duplicada",
};

function eventLabel(type: string): string {
  return EVENT_LABELS[(type ?? "").toUpperCase()] ?? type ?? "Evento";
}

// Glyphs for the timeline's system-event nodes — each maps to a semantic
// "what happened" cue so the thread reads like a narrative at a glance.
const EVENT_ICONS: Record<string, string> = {
  CREATED: "✦",
  ACK: "◎",
  ACKNOWLEDGED: "◎",
  ESCALATED: "▲",
  ASSIGNED: "↻",
  RESOLVED: "✓",
  COMMENT: "✎",
  COMMENT_ADDED: "✎",
  STATUS_CHANGED: "⇄",
  ALERT_DUPLICATE: "⚡",
};

function eventIcon(type: string): string {
  return EVENT_ICONS[(type ?? "").toUpperCase()] ?? "●";
}

/**
 * Timeline entry — a discriminated union merging events[] and comments[]
 * so both render through a single ordered thread.
 */
type TimelineEntry =
  | { kind: "event"; key: string; created_at: string; event: TicketEvent }
  | { kind: "comment"; key: string; created_at: string; comment: TicketComment };

/**
 * Merges events + comments into one chronological thread.
 *
 * Order: ascending by `created_at` (oldest → newest), matching how an
 * incident narrative is normally read top-to-bottom — "what happened first"
 * leads, "what happened most recently" trails (and sits closest to the
 * comment composer below it).
 */
function buildTimeline(events: TicketEvent[], comments: TicketComment[]): TimelineEntry[] {
  const entries: TimelineEntry[] = [
    ...events.map((event, i) => ({
      kind: "event" as const,
      key: `event-${i}-${event.created_at}`,
      created_at: event.created_at,
      event,
    })),
    ...comments.map((comment, i) => ({
      kind: "comment" as const,
      key: `comment-${i}-${comment.created_at}`,
      created_at: comment.created_at,
      comment,
    })),
  ];

  return entries.sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );
}

// ── Sub-components ───────────────────────────────────────────────

function Avatar({ name }: { name: string }) {
  return (
    <span className="assignee-avatar" aria-hidden="true">
      {initialsOf(name)}
    </span>
  );
}

function TimelineItem({ entry }: { entry: TimelineEntry }) {
  if (entry.kind === "comment") {
    const { comment } = entry;
    return (
      <li className="timeline-item timeline-item-comment">
        <span className="timeline-node timeline-node-comment" aria-hidden="true">
          <Avatar name={comment.author} />
        </span>
        <div className="timeline-body timeline-card timeline-card-comment">
          <div className="timeline-meta">
            <span className="timeline-author">{comment.author}</span>
            <span className="timeline-kind-tag timeline-kind-tag-comment">Comentario</span>
            <span className="timeline-time">{formatDateTime(comment.created_at)}</span>
          </div>
          <p className="timeline-comment-text">{comment.body}</p>
        </div>
      </li>
    );
  }

  const { event } = entry;
  return (
    <li className="timeline-item timeline-item-event">
      <span className="timeline-node timeline-node-event" aria-hidden="true">
        <span className="timeline-node-icon">{eventIcon(event.event_type)}</span>
      </span>
      <div className="timeline-body timeline-card timeline-card-event">
        <div className="timeline-meta">
          <span className="timeline-event-label">{eventLabel(event.event_type)}</span>
          <span className="timeline-kind-tag timeline-kind-tag-event">Sistema</span>
          {event.actor && <span className="timeline-author">{event.actor}</span>}
          <span className="timeline-time">{formatDateTime(event.created_at)}</span>
        </div>
        {event.action && <p className="timeline-event-detail">{event.action}</p>}
      </div>
    </li>
  );
}

// ── Page ─────────────────────────────────────────────────────────

export default function TicketDetail() {
  const { id } = useParams<{ id: string }>();
  const now = useNow();

  const [data, setData] = useState<TicketDetailData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  // Comment composer
  const [author, setAuthor] = useState<string>(() => localStorage.getItem(LS_ACTOR_KEY) ?? "");
  const [commentBody, setCommentBody] = useState("");
  const [isSubmittingComment, setIsSubmittingComment] = useState(false);
  const [commentError, setCommentError] = useState<string | null>(null);
  const [commentSuccess, setCommentSuccess] = useState(false);

  // Resolve action
  const [isResolving, setIsResolving] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [conflictNotice, setConflictNotice] = useState(false);

  // Generic status-transition action (ACK / ESCALATED)
  const [transitioningTo, setTransitioningTo] = useState<Status | null>(null);
  const [transitionError, setTransitionError] = useState<string | null>(null);

  // Reassign action
  const [reassignInput, setReassignInput] = useState("");
  const [isReassigning, setIsReassigning] = useState(false);
  const [reassignError, setReassignError] = useState<string | null>(null);

  // Tracks the in-flight refetch so a newer one cancels the previous (avoids
  // out-of-order responses clobbering state when actions fire in quick succession).
  const refetchAbortRef = useRef<AbortController | null>(null);

  // ── Load ticket ──────────────────────────────────────────────
  const load = useCallback(
    async (ticketId: string, signal: AbortSignal, isInitial: boolean) => {
      if (isInitial) {
        setIsLoading(true);
        setNotFound(false);
      } else {
        setIsRefreshing(true);
      }
      setError(null);

      try {
        const detail = await getTicket(ticketId, signal);
        if (signal.aborted) return;
        setData(detail);
      } catch (err) {
        if (signal.aborted) return;
        const message = err instanceof Error ? err.message : "Error al cargar el ticket";
        if (/404|not.?found/i.test(message)) {
          setNotFound(true);
        } else {
          setError(message);
        }
      } finally {
        if (!signal.aborted) {
          setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    },
    []
  );

  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    void load(id, controller.signal, true);
    return () => {
      controller.abort();
      refetchAbortRef.current?.abort();
    };
  }, [id, load]);

  const refetch = useCallback(() => {
    if (!id) return;
    // Cancel any refetch still in flight before starting a new one.
    refetchAbortRef.current?.abort();
    const controller = new AbortController();
    refetchAbortRef.current = controller;
    void load(id, controller.signal, false);
  }, [id, load]);

  // ── Timeline ─────────────────────────────────────────────────
  const timeline = useMemo(
    () => (data ? buildTimeline(data.events, data.comments) : []),
    [data]
  );

  // ── Comment submission ───────────────────────────────────────
  async function handleCommentSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!id || !data) return;

    const trimmedAuthor = author.trim();
    const trimmedBody = commentBody.trim();
    if (!trimmedAuthor || !trimmedBody) {
      setCommentError("Completa tu nombre y el comentario antes de enviarlo.");
      return;
    }

    setIsSubmittingComment(true);
    setCommentError(null);
    setCommentSuccess(false);

    try {
      await addComment(id, { author: trimmedAuthor, body: trimmedBody });
      localStorage.setItem(LS_ACTOR_KEY, trimmedAuthor);
      setCommentBody("");
      setCommentSuccess(true);

      // Optimistic append so the thread feels instant; refetch reconciles
      // with the server's canonical timestamp/ordering shortly after.
      setData((prev) =>
        prev
          ? {
              ...prev,
              comments: [
                ...prev.comments,
                { author: trimmedAuthor, body: trimmedBody, created_at: new Date().toISOString() },
              ],
            }
          : prev
      );
      refetch();
    } catch (err) {
      setCommentError(err instanceof Error ? err.message : "No se pudo publicar el comentario");
    } finally {
      setIsSubmittingComment(false);
    }
  }

  // ── Resolve ──────────────────────────────────────────────────
  async function handleResolve() {
    if (!id || !data || data.meta.status === "RESOLVED") return;

    const actor = author.trim() || data.meta.assignee;
    setIsResolving(true);
    setResolveError(null);
    setTransitionError(null);
    setReassignError(null);
    setConflictNotice(false);

    try {
      const result = await resolveTicket(id, { actor, version: data.meta.version });
      setData((prev) =>
        prev
          ? { ...prev, meta: { ...prev.meta, status: result.status, version: result.version } }
          : prev
      );
    } catch (err) {
      if (err instanceof VersionConflictError) {
        setConflictNotice(true);
        refetch();
      } else {
        setResolveError(err instanceof Error ? err.message : "No se pudo resolver el ticket");
      }
    } finally {
      setIsResolving(false);
    }
  }

  // ── Generic status transition (ACK / ESCALATED) ──────────────
  /**
   * handleTransition — transitions a ticket to `target` status via the
   * generic PATCH endpoint. Mirrors the handleResolve pattern exactly:
   *   actor = author field (trimmed) or the ticket's current assignee
   *   version = current meta.version for optimistic concurrency
   *   409 → conflictNotice + refetch (same banner as resolve)
   */
  async function handleTransition(target: Status) {
    if (!id || !data) return;
    if (data.meta.status === target || data.meta.status === "RESOLVED") return;

    const actor = author.trim() || data.meta.assignee;
    setTransitioningTo(target);
    setTransitionError(null);
    setResolveError(null);
    setReassignError(null);
    setConflictNotice(false);

    try {
      const result = await updateTicketStatus(id, {
        status: target,
        actor,
        version: data.meta.version,
      });
      setData((prev) =>
        prev
          ? { ...prev, meta: { ...prev.meta, status: result.status, version: result.version } }
          : prev
      );
      // Refresh so the new ACK/ESCALATED event shows up in the timeline at once.
      refetch();
    } catch (err) {
      if (err instanceof VersionConflictError) {
        setConflictNotice(true);
        refetch();
      } else {
        setTransitionError(err instanceof Error ? err.message : "No se pudo cambiar el estado");
      }
    } finally {
      setTransitioningTo(null);
    }
  }

  // ── Reassign ─────────────────────────────────────────────────
  async function handleReassign(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!id || !data) return;

    const newAssignee = reassignInput.trim();
    if (!newAssignee) return;
    if (newAssignee === data.meta.assignee) {
      setReassignError("El nuevo responsable es el mismo que el actual.");
      return;
    }

    const actor = author.trim() || data.meta.assignee;
    setIsReassigning(true);
    setReassignError(null);
    setResolveError(null);
    setTransitionError(null);
    setConflictNotice(false);

    try {
      const result = await reassignTicket(id, {
        assignee: newAssignee,
        actor,
        version: data.meta.version,
      });
      // Optimistic update — reflect the new assignee and version immediately.
      setData((prev) =>
        prev
          ? { ...prev, meta: { ...prev.meta, assignee: result.assignee, version: result.version } }
          : prev
      );
      setReassignInput("");
      // Trigger refetch so the ASSIGNED event appears in the timeline at once.
      refetch();
    } catch (err) {
      if (err instanceof VersionConflictError) {
        setConflictNotice(true);
        refetch();
      } else {
        setReassignError(err instanceof Error ? err.message : "No se pudo reasignar el ticket");
      }
    } finally {
      setIsReassigning(false);
    }
  }

  // ── Render: invalid route ────────────────────────────────────
  if (!id) {
    return (
      <div className="state-container" role="alert">
        <span className="state-icon" aria-hidden="true">⚠</span>
        <p className="state-title">Ticket no especificado</p>
        <Link to="/dashboard" className="btn-secondary">← Volver al dashboard</Link>
      </div>
    );
  }

  // ── Render: loading ──────────────────────────────────────────
  if (isLoading && !data) {
    return (
      <div className="state-container" role="status" aria-live="polite" aria-label="Cargando ticket">
        <Spinner size={22} />
        <p className="state-title">Cargando ticket {id}…</p>
      </div>
    );
  }

  // ── Render: not found ────────────────────────────────────────
  if (notFound) {
    return (
      <div className="state-container" role="alert">
        <span className="state-icon" aria-hidden="true">◫</span>
        <p className="state-title">Ticket no encontrado</p>
        <p className="state-subtitle">
          No existe ningún incidente con el identificador <strong>{id}</strong>.
        </p>
        <Link to="/dashboard" className="btn-secondary">← Volver al dashboard</Link>
      </div>
    );
  }

  // ── Render: hard error (no data yet) ─────────────────────────
  if (error && !data) {
    return (
      <div className="msg msg-error" role="alert" aria-live="assertive">
        <span className="msg-icon" aria-hidden="true">⚠</span>
        <div>
          <strong>Error al cargar el ticket</strong>
          <div style={{ marginTop: "var(--space-1)" }}>{error}</div>
          <div style={{ marginTop: "var(--space-3)" }}>
            <Link to="/dashboard" className="btn-secondary">← Volver al dashboard</Link>
          </div>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { meta, attachments } = data;
  const isResolved = meta.status === "RESOLVED";
  const remainingMs = new Date(meta.sla_deadline).getTime() - now;
  const slaIsBreached = !isResolved && remainingMs <= 0;

  return (
    <div className="ticket-detail-layout" aria-label={`Consola del ticket ${meta.ticket_id}`}>
      <Link to="/dashboard" className="btn-link ticket-detail-back">
        ← Volver al dashboard
      </Link>

      {/* ── Header: compact command bar ─────────────────────── */}
      {/* Row 1 (id-row): ticket ID · severity · status · ─ · SLA pill
          Row 2 (meta-row): title (truncated) · service · assignee · description
          No separate SLA "box" — the pill sits inline in row 1, so both
          rows are exactly as tall as their content. Zero dead space. */}
      <header className="ticket-detail-header">
        {/* ── Row 1 ── */}
        <div className="ticket-detail-id-row">
          <span className="ticket-id ticket-detail-id">{meta.ticket_id}</span>
          <span className="ticket-detail-id-divider" aria-hidden="true" />
          <SeverityBadge severity={meta.severity} />
          <StatusChip status={meta.status} />
          {typeof meta.occurrence_count === "number" && meta.occurrence_count > 1 && (
            <span
              className="ticket-detail-occurrence-badge"
              role="status"
              title={`Esta incidencia agrupa ${meta.occurrence_count} alertas duplicadas${meta.source ? ` (origen: ${meta.source})` : ""}`}
            >
              <span aria-hidden="true">⚡</span>
              ×{meta.occurrence_count} ocurrencias
            </span>
          )}

          {/* Right cluster — flat SLA pill + (if breached) the breach
              notice, both right-aligned inside row 1. The warning lives
              here instead of as a full-width strip below the header. */}
          <div className="ticket-detail-sla-cluster">
            <div
              className={
                "ticket-detail-sla-block" +
                (isResolved ? " ticket-detail-sla-block-frozen" : "") +
                (slaIsBreached ? " ticket-detail-sla-block-breached" : "")
              }
            >
              <span className="ticket-detail-sla-label">
                <span className="ticket-detail-sla-label-icon" aria-hidden="true">
                  {isResolved ? "❄" : "◷"}
                </span>
                {isResolved ? "SLA congelado" : "SLA restante"}
              </span>
              {isResolved ? (
                <span className="sla-countdown sla-ok ticket-detail-sla-frozen" role="status">
                  <span className="sla-countdown-icon" aria-hidden="true">✓</span>
                  Resuelto antes del límite
                </span>
              ) : (
                <SlaCountdown deadline={meta.sla_deadline} />
              )}
            </div>

            {slaIsBreached && (
              <div className="ticket-detail-sla-warning" role="alert">
                <span className="msg-icon" aria-hidden="true">⚠</span>
                <span>Este ticket superó su SLA — prioriza su resolución.</span>
              </div>
            )}
          </div>
        </div>

        {/* ── Row 2 ── */}
        <div className="ticket-detail-meta-row">
          <h1 className="ticket-detail-title" title={meta.title}>{meta.title}</h1>
          <div className="ticket-detail-subline">
            <span className="ticket-service">{meta.service}</span>
            <span className="ticket-detail-dot" aria-hidden="true">·</span>
            <div className="ticket-assignee ticket-detail-assignee">
              <Avatar name={meta.assignee} />
              <span className="assignee-name">{meta.assignee}</span>
            </div>
          </div>
        </div>

        {/* ── Row 3: the ticket message — the centerpiece, kept legible ── */}
        <p className="ticket-detail-description" title={meta.description}>
          {meta.description}
        </p>
      </header>

      {isRefreshing && (
        <div className="ticket-detail-refresh-pill" role="status" aria-live="polite">
          <Spinner size={10} />
          Actualizando…
        </div>
      )}

      {error && data && (
        <div className="msg msg-error" role="alert" aria-live="assertive">
          <span className="msg-icon" aria-hidden="true">⚠</span>
          <div>{error}</div>
        </div>
      )}

      <div className="ticket-detail-grid">
        {/* ── Main column: composer (top) + timeline (fills the rest) ── */}
        <div className="ticket-detail-main">
          {/* ── Comment composer ─────────────────────────────── */}
          <section className="ticket-detail-panel ticket-detail-composer-panel" aria-labelledby="ticket-comment-heading">
            <h2 id="ticket-comment-heading" className="ticket-detail-panel-title">
              <span className="ticket-detail-panel-title-icon" aria-hidden="true">✎</span>
              Agregar comentario
            </h2>
            <form className="ticket-comment-form" onSubmit={handleCommentSubmit} noValidate>
              <div className="ticket-comment-form-grid">
                <div className="composer-field ticket-comment-author-field">
                  <div className="composer-field-head">
                    <label htmlFor="comment-author" className="composer-field-label">Tu nombre</label>
                  </div>
                  <input
                    id="comment-author"
                    type="text"
                    value={author}
                    onChange={(e) => setAuthor(e.target.value)}
                    placeholder="p. ej. Ana López"
                    autoComplete="off"
                    required
                  />
                </div>

                <div className="composer-field">
                  <div className="composer-field-head">
                    <label htmlFor="comment-body" className="composer-field-label">Comentario</label>
                  </div>
                  <textarea
                    id="comment-body"
                    className="composer-textarea ticket-comment-textarea"
                    value={commentBody}
                    onChange={(e) => {
                      setCommentBody(e.target.value);
                      setCommentSuccess(false);
                    }}
                    placeholder="Escribe una actualización para el equipo…"
                    rows={2}
                    required
                  />
                </div>
              </div>

              {commentError && (
                <div className="msg msg-error" role="alert" aria-live="assertive">
                  <span className="msg-icon" aria-hidden="true">⚠</span>
                  <div>{commentError}</div>
                </div>
              )}
              {commentSuccess && !commentError && (
                <div className="msg msg-success" role="status" aria-live="polite">
                  <span className="msg-icon" aria-hidden="true">✓</span>
                  <div>Comentario publicado.</div>
                </div>
              )}

              <div className="ticket-comment-form-actions">
                <span className="ticket-comment-hint">
                  Tu nombre queda guardado para tus próximos comentarios.
                </span>
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={isSubmittingComment || !author.trim() || !commentBody.trim()}
                  aria-busy={isSubmittingComment}
                >
                  {isSubmittingComment ? (
                    <span className="btn-primary-loading">
                      <Spinner size={12} />
                      Publicando…
                    </span>
                  ) : (
                    "Publicar comentario"
                  )}
                </button>
              </div>
            </form>
          </section>

          <section className="ticket-detail-panel ticket-detail-timeline-panel" aria-labelledby="ticket-timeline-heading">
            <div className="ticket-detail-panel-header">
              <h2 id="ticket-timeline-heading" className="ticket-detail-panel-title">
                <span className="ticket-detail-panel-title-icon" aria-hidden="true">▤</span>
                Cronología
              </h2>
              <span className="table-panel-meta">
                {timeline.length} evento{timeline.length !== 1 ? "s" : ""} · orden cronológico ascendente
              </span>
            </div>

            {timeline.length === 0 ? (
              <p className="empty-msg">Aún no hay eventos ni comentarios registrados.</p>
            ) : (
              <ol className="timeline-list" aria-label="Cronología de eventos y comentarios">
                {timeline.map((entry) => (
                  <TimelineItem key={entry.key} entry={entry} />
                ))}
              </ol>
            )}
          </section>
        </div>

        {/* ── Side panel ───────────────────────────────────── */}
        <aside className="ticket-detail-side" aria-label="Información del ticket">
          <section className="ticket-detail-panel ticket-detail-actions-panel">
            <h2 className="ticket-detail-panel-title">
              <span className="ticket-detail-panel-title-icon" aria-hidden="true">⚡</span>
              Acciones
            </h2>

            {conflictNotice && (
              <div className="msg msg-info" role="status" aria-live="polite">
                <span className="msg-icon" aria-hidden="true">↻</span>
                <div>El ticket cambió de versión — recargando los datos más recientes…</div>
              </div>
            )}
            {resolveError && (
              <div className="msg msg-error" role="alert" aria-live="assertive">
                <span className="msg-icon" aria-hidden="true">⚠</span>
                <div>{resolveError}</div>
              </div>
            )}
            {transitionError && (
              <div className="msg msg-error" role="alert" aria-live="assertive">
                <span className="msg-icon" aria-hidden="true">⚠</span>
                <div>{transitionError}</div>
              </div>
            )}

            {/* ── Reconocer (ACK) ─────────────────────────── */}
            {/* Enabled: OPEN or ESCALATED. Shown as inactive when already ACK.
                Hidden / no-op when RESOLVED (the whole panel is terminal). */}
            {meta.status !== "RESOLVED" && (
              <button
                type="button"
                className="btn-secondary ticket-detail-ack-btn"
                onClick={() => handleTransition("ACK")}
                disabled={meta.status === "ACK" || isResolving || transitioningTo !== null}
                aria-busy={transitioningTo === "ACK"}
              >
                {transitioningTo === "ACK" ? (
                  <span className="btn-primary-loading">
                    <Spinner size={12} />
                    Reconociendo…
                  </span>
                ) : meta.status === "ACK" ? (
                  <>
                    <span aria-hidden="true">◎</span> Reconocido
                  </>
                ) : (
                  <>
                    <span aria-hidden="true">◎</span> Reconocer (ACK)
                  </>
                )}
              </button>
            )}

            {/* ── Escalar ─────────────────────────────────── */}
            {/* Enabled: OPEN or ACK. Shown as inactive when already ESCALATED.
                Hidden / no-op when RESOLVED. */}
            {meta.status !== "RESOLVED" && (
              <button
                type="button"
                className="btn-secondary ticket-detail-escalate-btn"
                onClick={() => handleTransition("ESCALATED")}
                disabled={meta.status === "ESCALATED" || isResolving || transitioningTo !== null}
                aria-busy={transitioningTo === "ESCALATED"}
              >
                {transitioningTo === "ESCALATED" ? (
                  <span className="btn-primary-loading">
                    <Spinner size={12} />
                    Escalando…
                  </span>
                ) : meta.status === "ESCALATED" ? (
                  <>
                    <span aria-hidden="true">▲</span> Escalado
                  </>
                ) : (
                  <>
                    <span aria-hidden="true">▲</span> Escalar
                  </>
                )}
              </button>
            )}

            {/* ── Resolver ticket (primary — keeps exact text/role from M3) ── */}
            <button
              type="button"
              className="btn-primary ticket-detail-resolve-btn"
              onClick={handleResolve}
              disabled={isResolved || isResolving || transitioningTo !== null}
              aria-busy={isResolving}
            >
              {isResolving ? (
                <span className="btn-primary-loading">
                  <Spinner size={12} />
                  Resolviendo…
                </span>
              ) : isResolved ? (
                <>
                  <span aria-hidden="true">✓</span> Ticket resuelto
                </>
              ) : (
                "Resolver ticket"
              )}
            </button>
            <p className="composer-hint">
              {isResolved
                ? "Este ticket ya está marcado como RESOLVED; el SLA quedó congelado."
                : "Marca el ticket como resuelto. Se valida la versión para evitar sobrescribir cambios concurrentes."}
            </p>
          </section>

          <section className="ticket-detail-panel" aria-labelledby="ticket-info-heading">
            <h2 id="ticket-info-heading" className="ticket-detail-panel-title">
              <span className="ticket-detail-panel-title-icon" aria-hidden="true">ℹ</span>
              Detalles
            </h2>
            <dl className="ticket-detail-info-list">
              <div className="ticket-detail-info-row">
                <dt>Severidad</dt>
                <dd><SeverityBadge severity={meta.severity} /></dd>
              </div>
              <div className="ticket-detail-info-row">
                <dt>Estado</dt>
                <dd><StatusChip status={meta.status} /></dd>
              </div>
              <div className="ticket-detail-info-row">
                <dt>Vencimiento SLA</dt>
                <dd>{formatDateTime(meta.sla_deadline)}</dd>
              </div>
              <div className="ticket-detail-info-row">
                <dt>Creado</dt>
                <dd>{formatDateTime(meta.created_at)}</dd>
              </div>
              <div className="ticket-detail-info-row">
                <dt>Actualizado</dt>
                <dd>{formatDateTime(meta.updated_at)}</dd>
              </div>
              <div className="ticket-detail-info-row">
                <dt>Versión</dt>
                <dd><span className="ticket-id">v{meta.version}</span></dd>
              </div>
            </dl>

            {/* ── Reasignar responsable ────────────────────── */}
            <form
              className="ticket-reassign-form"
              onSubmit={handleReassign}
              noValidate
              aria-label="Reasignar responsable"
            >
              <label htmlFor="reassign-input" className="ticket-reassign-label">
                Reasignar a
              </label>
              <div className="ticket-reassign-row">
                <input
                  id="reassign-input"
                  type="text"
                  value={reassignInput}
                  onChange={(e) => {
                    setReassignInput(e.target.value);
                    setReassignError(null);
                  }}
                  placeholder={meta.assignee}
                  disabled={isResolved || isReassigning}
                  autoComplete="off"
                  aria-label="Nuevo responsable"
                />
                <button
                  type="submit"
                  className="btn-secondary ticket-reassign-btn"
                  disabled={
                    isResolved ||
                    isReassigning ||
                    !reassignInput.trim() ||
                    reassignInput.trim() === meta.assignee
                  }
                  aria-busy={isReassigning}
                >
                  {isReassigning ? (
                    <span className="btn-primary-loading">
                      <Spinner size={12} />
                      Reasignando…
                    </span>
                  ) : (
                    "Reasignar"
                  )}
                </button>
              </div>
              {reassignError && (
                <div className="msg msg-error" role="alert" aria-live="assertive">
                  <span className="msg-icon" aria-hidden="true">⚠</span>
                  <div>{reassignError}</div>
                </div>
              )}
              {isResolved && (
                <p className="composer-hint">
                  No es posible reasignar un ticket RESOLVED.
                </p>
              )}
            </form>
          </section>

          <section className="ticket-detail-panel" aria-labelledby="ticket-attachments-heading">
            <h2 id="ticket-attachments-heading" className="ticket-detail-panel-title">
              <span className="ticket-detail-panel-title-icon" aria-hidden="true">⌲</span>
              Adjuntos
              <span className="table-panel-status-pill" style={{ marginLeft: "var(--space-2)" }}>
                {meta.attachments_count}
              </span>
            </h2>
            {attachments.length === 0 ? (
              <p className="empty-msg">Este ticket no tiene archivos adjuntos.</p>
            ) : (
              <ul className="ticket-attachment-list">
                {attachments.map((att, i) => {
                  const size = formatBytes(att.size);
                  return (
                    <li key={`${att.filename}-${i}`} className="ticket-attachment-item">
                      <span className="ticket-attachment-icon" aria-hidden="true">{attachmentGlyph(att.filename)}</span>
                      <div className="ticket-attachment-meta">
                        <span className="ticket-attachment-name" title={att.filename}>
                          {att.filename}
                        </span>
                        {size && <span className="ticket-attachment-size">{size}</span>}
                      </div>
                      <span className="ticket-attachment-ext" aria-hidden="true">
                        {extensionOf(att.filename)}
                      </span>
                      {att.download_url && (
                        <a
                          href={att.download_url}
                          download={att.filename}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="ticket-attachment-download-link"
                          aria-label={`Descargar ${att.filename}`}
                        >
                          ↓
                        </a>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
