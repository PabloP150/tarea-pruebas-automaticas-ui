export type Severity = "P0" | "P1" | "P2";
export type Status = "OPEN" | "ACK" | "ESCALATED" | "RESOLVED";

export interface CreateTicketInput {
  title: string;
  service: string;
  description: string;
  severity?: Severity;
  assignee?: string;
  attachment?: { filename: string; content_type: string };
}

export interface CreateTicketResponse {
  ticket_id: string;
  status: Status;
  sla_deadline: string;
  upload_url?: string;
}

export interface DashboardItem {
  ticket_id: string;
  severity: Severity;
  status: Status;
  title: string;
  service: string;
  assignee: string;
  sla_deadline: string;
}

// ── M3 — Ticket detail / console ──────────────────────────────────

export interface TicketMeta {
  ticket_id: string;
  title: string;
  service: string;
  description: string;
  severity: Severity;
  status: Status;
  assignee: string;
  sla_deadline: string;
  created_at: string;
  updated_at: string;
  version: number;
  attachments_count: number;
  /** Present on tickets created via the webhook-ingesta path (US-02). */
  occurrence_count?: number;
  source?: string;
  dedup_hash?: string;
}

/** A lifecycle event recorded on the ticket timeline (e.g. CREATED, ACK, RESOLVED). */
export interface TicketEvent {
  event_type: string;
  actor?: string;
  action?: string;
  payload?: Record<string, unknown>;
  created_at: string;
}

export interface TicketComment {
  author: string;
  body: string;
  created_at: string;
}

export interface TicketAttachment {
  filename: string;
  content_type?: string;
  size?: number;
  created_at?: string;
  /** Presigned GET URL (5 min TTL) returned by GET /api/v1/incidents/{id}. */
  download_url?: string;
}

export interface TicketDetail {
  meta: TicketMeta;
  events: TicketEvent[];
  comments: TicketComment[];
  attachments: TicketAttachment[];
}

export interface AddCommentInput {
  author: string;
  body: string;
}

export interface ResolveTicketInput {
  actor: string;
  version: number;
}

export interface ResolveTicketResponse {
  status: Status;
  version: number;
}
