import type {
  AddCommentInput,
  CreateTicketInput,
  CreateTicketResponse,
  DashboardItem,
  ResolveTicketInput,
  ResolveTicketResponse,
  Status,
  TicketDetail,
} from "../types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

/**
 * VersionConflictError — thrown by `resolveTicket` when the server responds
 * 409 (optimistic-concurrency conflict: the `version` sent no longer matches
 * the stored ticket). Callers can `instanceof`-check this to show a
 * "the ticket changed, refreshing…" notice and refetch, instead of treating
 * it as a generic failure (contract: ARCHITECTURE.md §6 — PATCH 409).
 */
export class VersionConflictError extends Error {
  readonly isVersionConflict = true as const;

  constructor(message = "El ticket cambió de versión — actualiza para continuar") {
    super(message);
    this.name = "VersionConflictError";
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (data?.error) message = data.error;
      else if (data?.message) message = data.message;
    } catch {
      // ignore JSON parse error — keep the HTTP status message
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export async function createTicket(input: CreateTicketInput): Promise<CreateTicketResponse> {
  const res = await fetch(`${BASE}/api/v1/incidents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return handleResponse<CreateTicketResponse>(res);
}

/**
 * listDashboard — accepts an optional AbortSignal so callers can cancel
 * in-flight requests when filters change (IMP-06 race condition fix).
 *
 * When `assignee` is empty/whitespace the param is omitted entirely, causing
 * the backend to return ALL tickets in that state (not filtered by engineer).
 */
export async function listDashboard(
  assignee: string,
  status: string,
  signal?: AbortSignal
): Promise<DashboardItem[]> {
  const params = new URLSearchParams({ status });
  if (assignee.trim()) params.set("assignee", assignee.trim());
  const res = await fetch(`${BASE}/api/v1/incidents?${params.toString()}`, {
    signal,
  });
  const data = await handleResponse<{ items: DashboardItem[] }>(res);
  return data.items;
}

// ── M3 — Ticket detail / console ──────────────────────────────────

/**
 * getTicket — fetches the full incident console payload (meta, timeline
 * events, comments, attachments). Accepts an AbortSignal so the page can
 * cancel in-flight requests on unmount or id change.
 */
export async function getTicket(id: string, signal?: AbortSignal): Promise<TicketDetail> {
  const res = await fetch(`${BASE}/api/v1/incidents/${encodeURIComponent(id)}`, { signal });
  return handleResponse<TicketDetail>(res);
}

/**
 * addComment — posts a new comment on the ticket thread.
 * Returns void; the contract only guarantees `{ok:true}` on 201, so the
 * caller is expected to refetch (or append optimistically) afterwards.
 */
export async function addComment(id: string, input: AddCommentInput): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/incidents/${encodeURIComponent(id)}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  await handleResponse<{ ok: boolean }>(res);
}

export interface UpdateTicketStatusInput {
  status: Status;
  actor: string;
  version: number;
}

/**
 * updateTicketStatus — generic PATCH that transitions a ticket to any allowed
 * status using optimistic concurrency (`version` must match the server's
 * current value).
 *
 * Allowed transitions per the state machine (ARCHITECTURE.md §6):
 *   OPEN → {ACK, ESCALATED, RESOLVED}
 *   ACK  → {ESCALATED, RESOLVED}
 *   ESCALATED → {ACK, RESOLVED}
 *   RESOLVED → terminal
 *
 * On 409 throws `VersionConflictError`; on 400 throws a generic Error with the
 * server's message (invalid transition). Callers should `instanceof`-check for
 * the 409 case to show a "ticket changed, refetching" notice.
 */
export async function updateTicketStatus(
  id: string,
  input: UpdateTicketStatusInput,
  signal?: AbortSignal
): Promise<ResolveTicketResponse> {
  const res = await fetch(`${BASE}/api/v1/incidents/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: input.status, actor: input.actor, version: input.version }),
    signal,
  });

  if (res.status === 409) {
    throw new VersionConflictError();
  }

  return handleResponse<ResolveTicketResponse>(res);
}

/**
 * resolveTicket — convenience wrapper over `updateTicketStatus` that always
 * transitions to RESOLVED. Kept for backward compatibility with existing
 * call sites and test mocks.
 */
export async function resolveTicket(
  id: string,
  input: ResolveTicketInput
): Promise<ResolveTicketResponse> {
  return updateTicketStatus(id, { status: "RESOLVED", actor: input.actor, version: input.version });
}

export interface ReassignTicketInput {
  assignee: string;
  actor: string;
  version: number;
}

export interface ReassignTicketResponse {
  assignee: string;
  version: number;
}

/**
 * reassignTicket — PATCHes /api/v1/incidents/{id}/assignee with optimistic
 * concurrency. The `version` must match the server's current value.
 *
 * On 409 throws `VersionConflictError` (same pattern as updateTicketStatus).
 * On 400 throws a generic Error with the server's message (ticket RESOLVED
 * or missing fields). Accepts an optional AbortSignal for cancellation.
 */
export async function reassignTicket(
  id: string,
  input: ReassignTicketInput,
  signal?: AbortSignal
): Promise<ReassignTicketResponse> {
  const res = await fetch(
    `${BASE}/api/v1/incidents/${encodeURIComponent(id)}/assignee`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        assignee: input.assignee,
        actor: input.actor,
        version: input.version,
      }),
      signal,
    }
  );

  if (res.status === 409) {
    throw new VersionConflictError();
  }

  return handleResponse<ReassignTicketResponse>(res);
}
