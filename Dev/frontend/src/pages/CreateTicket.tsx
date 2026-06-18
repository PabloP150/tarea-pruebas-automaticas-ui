import { useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { createTicket } from "../api/client";
import type { Severity, CreateTicketResponse } from "../types";
import StatusChip from "../components/StatusChip";

// ── Static reference data ──────────────────────────────────────

const SERVICES: { value: string; icon: string }[] = [
  { value: "ERP",         icon: "▣" },
  { value: "Pagos",       icon: "◈" },
  { value: "Red",         icon: "◌" },
  { value: "Impresoras",  icon: "▤" },
  { value: "Correo",      icon: "✉" },
];

const SEVERITIES: {
  value: Severity;
  label: string;
  shortDesc: string;
  slaLabel: string;
  slaMinutes: number;
}[] = [
  { value: "P0", label: "P0", shortDesc: "Crítico — caída total", slaLabel: "15 min", slaMinutes: 15 },
  { value: "P1", label: "P1", shortDesc: "Alto — degradación",    slaLabel: "4 h",     slaMinutes: 240 },
  { value: "P2", label: "P2", shortDesc: "Normal — sin urgencia", slaLabel: "24 h",    slaMinutes: 1440 },
];

const TITLE_LIMIT = 200;
const DESCRIPTION_LIMIT = 4000;

// ── Helpers ─────────────────────────────────────────────────────

function initialsOf(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "—";
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function formatDeadline(d: Date): string {
  return d.toLocaleString("es-GT", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRelative(minutes: number): string {
  if (minutes < 60) return `en ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (rest === 0) return `en ${hours} h`;
  return `en ${hours} h ${rest} min`;
}

// ── Component ───────────────────────────────────────────────────

export default function CreateTicket() {
  const [title,       setTitle]       = useState("");
  const [service,     setService]     = useState(SERVICES[0].value);
  const [description, setDescription] = useState("");
  const [severity,    setSeverity]    = useState<Severity>("P2");
  const [assignee,    setAssignee]    = useState("");
  const [file,        setFile]        = useState<File | null>(null);
  const [isDragging,  setIsDragging]  = useState(false);

  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [result,  setResult]  = useState<CreateTicketResponse | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const selectedSeverity = SEVERITIES.find((s) => s.value === severity) ?? SEVERITIES[2];

  // Live SLA projection for the preview — computed client-side from "now"
  const slaProjection = useMemo(() => {
    const now = new Date();
    const deadline = new Date(now.getTime() + selectedSeverity.slaMinutes * 60_000);
    return {
      deadline,
      label: formatDeadline(deadline),
      relative: formatRelative(selectedSeverity.slaMinutes),
    };
  }, [selectedSeverity]);

  // Completion meter — purely cosmetic, but genuinely reflects field state
  const completion = useMemo(() => {
    let filled = 0;
    const total = 5;
    if (title.trim()) filled++;
    if (description.trim()) filled++;
    if (service) filled++;
    if (severity) filled++;
    if (assignee.trim() || file) filled++;
    return Math.round((filled / total) * 100);
  }, [title, description, service, severity, assignee, file]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!title.trim())       { setError("El título del incidente es requerido."); return; }
    if (!description.trim()) { setError("La descripción es requerida para el diagnóstico."); return; }

    setLoading(true);
    try {
      const input = {
        title:       title.trim(),
        service,
        description: description.trim(),
        severity,
        ...(assignee.trim() ? { assignee: assignee.trim() } : {}),
        ...(file
          ? { attachment: { filename: file.name, content_type: file.type || "application/octet-stream" } }
          : {}),
      };

      const resp = await createTicket(input);

      if (resp.upload_url && file) {
        try {
          await fetch(resp.upload_url, {
            method: "PUT",
            headers: { "Content-Type": file.type || "application/octet-stream" },
            body: file,
          });
        } catch {
          // silently ignored — moto presigned PUT may fail
        }
      }

      setResult(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido al emitir el ticket.");
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setResult(null);
    setTitle("");
    setDescription("");
    setAssignee("");
    setFile(null);
    setSeverity("P2");
    setError(null);
  }

  // Cmd/Ctrl+Enter submits from anywhere inside the composer
  function handleComposerKeyDown(e: KeyboardEvent<HTMLFormElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      formRef.current?.requestSubmit();
    }
  }

  function handleFileChosen(chosen: File | null | undefined) {
    setFile(chosen ?? null);
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) handleFileChosen(dropped);
  }

  // ── Success state ───────────────────────────────────────────
  if (result) {
    return (
      <div className="form-page form-page-success">
        <div className="card">
          <div className="success-card">

            <div className="success-icon-wrap" aria-hidden="true">
              <div className="success-icon-ring">
                <div className="success-icon-inner">✓</div>
              </div>
            </div>

            <h2 className="success-title">Ticket emitido correctamente</h2>
            <p className="success-subtitle">
              El incidente ha sido registrado y el SLA comenzó a contarse.
            </p>

            <div className="success-meta">
              <div className="success-meta-row">
                <span className="success-meta-label">ID</span>
                <span className="success-ticket-id">{result.ticket_id}</span>
              </div>
              <div className="success-meta-row">
                <span className="success-meta-label">Estado</span>
                <span className="success-meta-value">
                  <StatusChip status={result.status} />
                </span>
              </div>
              <div className="success-meta-row">
                <span className="success-meta-label">SLA límite</span>
                <span className="success-meta-value">
                  {new Date(result.sla_deadline).toLocaleString("es-GT", {
                    day: "2-digit", month: "short", year: "numeric",
                    hour: "2-digit", minute: "2-digit",
                  })}
                </span>
              </div>
              {result.upload_url && (
                <div className="success-meta-row">
                  <span className="success-meta-label">Adjunto</span>
                  <span className="note">URL presigned generada</span>
                </div>
              )}
            </div>

            <div className="success-actions">
              <button onClick={handleReset} className="btn-secondary">
                Emitir otro ticket
              </button>
              <Link to="/dashboard" className="btn-primary">
                Ver en Dashboard
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Composer state ──────────────────────────────────────────
  return (
    <div className="composer">
      <form
        ref={formRef}
        onSubmit={handleSubmit}
        onKeyDown={handleComposerKeyDown}
        noValidate
        aria-label="Compositor de nuevo ticket operativo"
        className="composer-grid"
      >

        {/* ── Column 1: Severity + meta controls ──────────────── */}
        <section className="composer-col composer-col-severity" aria-label="Severidad y prioridad">
          <header className="composer-col-header">
            <span className="composer-col-eyebrow">01 · Prioridad</span>
            <h2 className="composer-col-title">¿Qué tan grave es?</h2>
          </header>

          <div className="severity-stack" role="radiogroup" aria-label="Nivel de severidad del incidente">
            {SEVERITIES.map(({ value, label, shortDesc, slaLabel }) => {
              const checked = severity === value;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={checked}
                  id={`sev-${value}`}
                  className={`sev-card sev-card-${value.toLowerCase()}${checked ? " is-selected" : ""}`}
                  onClick={() => setSeverity(value)}
                >
                  <span className="sev-card-glyph" aria-hidden="true">{label}</span>
                  <span className="sev-card-body">
                    <span className="sev-card-name">{label} · {shortDesc.split(" — ")[0]}</span>
                    <span className="sev-card-desc">{shortDesc.split(" — ")[1]}</span>
                  </span>
                  <span className="sev-card-sla">
                    <span className="sev-card-sla-value">{slaLabel}</span>
                    <span className="sev-card-sla-label">SLA</span>
                  </span>
                </button>
              );
            })}
          </div>

          <div className="composer-progress" aria-hidden="true">
            <div className="composer-progress-head">
              <span>Completitud</span>
              <span className="composer-progress-pct">{completion}%</span>
            </div>
            <div className="composer-progress-track">
              <div className="composer-progress-fill" style={{ width: `${completion}%` }} />
            </div>
          </div>

          <div className="composer-shortcut" aria-hidden="true">
            <kbd>⌘</kbd><span>+</span><kbd>Enter</kbd>
            <span className="composer-shortcut-label">para emitir al instante</span>
          </div>
        </section>

        {/* ── Column 2: main composition canvas ────────────────── */}
        <section className="composer-col composer-col-main" aria-label="Detalles del incidente">
          <header className="composer-col-header">
            <span className="composer-col-eyebrow">02 · Diagnóstico</span>
            <h2 className="composer-col-title">Cuéntanos qué pasó</h2>
          </header>

          {error && (
            <div className="error-msg" role="alert" aria-live="assertive">
              <span className="msg-icon" aria-hidden="true">⚠</span>
              <span>{error}</span>
            </div>
          )}

          <div className="composer-field">
            <div className="composer-field-head">
              <label htmlFor="title" className="field-required">Título del incidente</label>
              <span className="composer-counter" data-warn={title.length > TITLE_LIMIT * 0.9 ? "true" : "false"}>
                {title.length}/{TITLE_LIMIT}
              </span>
            </div>
            <input
              id="title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value.slice(0, TITLE_LIMIT))}
              placeholder="Ej: Caída del servicio de Pagos en producción"
              required
              autoFocus
              maxLength={TITLE_LIMIT}
              aria-required="true"
            />
          </div>

          <div className="composer-field">
            <div className="composer-field-head">
              <label htmlFor="description" className="field-required">Descripción del incidente</label>
              <span className="composer-counter" data-warn={description.length > DESCRIPTION_LIMIT * 0.9 ? "true" : "false"}>
                {description.length}/{DESCRIPTION_LIMIT}
              </span>
            </div>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value.slice(0, DESCRIPTION_LIMIT))}
              placeholder="Describe los síntomas, impacto y cualquier contexto relevante para el diagnóstico."
              required
              maxLength={DESCRIPTION_LIMIT}
              aria-required="true"
              className="composer-textarea"
            />
          </div>

          <div className="composer-field">
            <span className="composer-field-label" id="service-label">Servicio afectado</span>
            <div className="service-chips" role="radiogroup" aria-labelledby="service-label">
              {SERVICES.map(({ value, icon }) => {
                const checked = service === value;
                return (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={checked}
                    className={`service-chip${checked ? " is-selected" : ""}`}
                    onClick={() => setService(value)}
                  >
                    <span className="service-chip-icon" aria-hidden="true">{icon}</span>
                    {value}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="composer-row">
            <div className="composer-field composer-field-assignee">
              <label htmlFor="assignee" className="composer-field-label">
                Asignado <span className="composer-optional">(opcional)</span>
              </label>
              <div className="assignee-input-wrap">
                <span className="assignee-preview-avatar" aria-hidden="true">
                  {initialsOf(assignee)}
                </span>
                <input
                  id="assignee"
                  type="text"
                  value={assignee}
                  onChange={(e) => setAssignee(e.target.value)}
                  placeholder="Nombre del ingeniero"
                  aria-describedby="assignee-hint"
                />
              </div>
              <span id="assignee-hint" className="composer-hint">
                Vacío → se asigna a UNASSIGNED
              </span>
            </div>

            <div className="composer-field composer-field-attachment">
              <span className="composer-field-label">
                Adjunto <span className="composer-optional">(opcional)</span>
              </span>
              <div
                className={`dropzone${isDragging ? " is-dragging" : ""}${file ? " has-file" : ""}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={handleDrop}
                role="button"
                tabIndex={0}
                aria-label={file ? `Archivo adjunto: ${file.name}. Clic para cambiar.` : "Arrastra un archivo aquí o haz clic para seleccionarlo"}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    fileInputRef.current?.click();
                  }
                }}
              >
                <input
                  ref={fileInputRef}
                  id="attachment"
                  type="file"
                  className="dropzone-input"
                  onChange={(e) => handleFileChosen(e.target.files?.[0])}
                  aria-label="Seleccionar archivo adjunto"
                  tabIndex={-1}
                />
                <span className="dropzone-icon" aria-hidden="true">{file ? "✓" : "⤓"}</span>
                <span className="dropzone-text">
                  {file ? file.name : "Suelta un archivo o haz clic"}
                </span>
                <span className="dropzone-hint">
                  {file ? `${(file.size / 1024).toFixed(1)} KB` : "PNG, JPG, PDF, ZIP — hasta 10 MB"}
                </span>
              </div>
            </div>
          </div>

          <div className="composer-actions">
            <span className="composer-required-note">* Campos requeridos</span>
            <button
              type="submit"
              disabled={loading}
              className="btn-primary btn-emit"
              aria-busy={loading}
            >
              {loading ? (
                <span className="btn-primary-loading">
                  <span className="spinner" aria-hidden="true" />
                  Emitiendo…
                </span>
              ) : (
                <>
                  <span aria-hidden="true">⚡</span>
                  Emitir Ticket Operativo
                </>
              )}
            </button>
          </div>
        </section>

        {/* ── Column 3: live preview ────────────────────────────── */}
        <aside className="composer-col composer-col-preview" aria-label="Vista previa en vivo del ticket">
          <header className="composer-col-header">
            <span className="composer-col-eyebrow">03 · Vista previa</span>
            <h2 className="composer-col-title">Así se verá tu ticket</h2>
          </header>

          <div className={`preview-card preview-card-${severity.toLowerCase()}`} aria-live="polite">
            <div className="preview-card-top">
              <span className={`severity-badge severity-badge-${severity.toLowerCase()}`}>
                <span className="severity-badge-dot" aria-hidden="true" />
                {severity}
              </span>
              <span className="preview-status-chip" aria-hidden="true">
                <StatusChip status="OPEN" />
              </span>
            </div>

            <h3 className="preview-card-title">
              {title.trim() || "Título de tu incidente aparecerá aquí…"}
            </h3>

            <p className="preview-card-desc">
              {description.trim()
                ? (description.length > 140 ? `${description.slice(0, 140)}…` : description)
                : "La descripción del diagnóstico se mostrará en esta vista previa conforme escribas."}
            </p>

            <div className="preview-card-meta">
              <span className="preview-meta-chip">
                <span className="preview-meta-icon" aria-hidden="true">▣</span>
                {service}
              </span>
              <span className="preview-meta-chip preview-meta-assignee">
                <span className="assignee-avatar" aria-hidden="true">{initialsOf(assignee)}</span>
                {assignee.trim() || "UNASSIGNED"}
              </span>
              {file && (
                <span className="preview-meta-chip">
                  <span className="preview-meta-icon" aria-hidden="true">⌾</span>
                  {file.name.length > 18 ? `${file.name.slice(0, 16)}…` : file.name}
                </span>
              )}
            </div>

            <div className="preview-sla">
              <div className="preview-sla-row">
                <span className="preview-sla-label">SLA de respuesta</span>
                <span className="preview-sla-window">{selectedSeverity.slaLabel}</span>
              </div>
              <div className="preview-sla-deadline">
                <span className="preview-sla-icon" aria-hidden="true">◷</span>
                Vence ~{slaProjection.label} · {slaProjection.relative}
              </div>
            </div>
          </div>

          <div className="preview-footnote">
            <span className="preview-footnote-dot" aria-hidden="true" />
            Esta proyección se actualiza en vivo según tus respuestas. El SLA real
            comienza a contar en el instante en que emites el ticket.
          </div>
        </aside>
      </form>
    </div>
  );
}
