import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import TicketDetail from "./TicketDetail";
import type { TicketDetail as TicketDetailData } from "../types";

// ── Module mock for api/client ────────────────────────────────────

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    getTicket: vi.fn(),
    addComment: vi.fn(),
    resolveTicket: vi.fn(),
    updateTicketStatus: vi.fn(),
    reassignTicket: vi.fn(),
    VersionConflictError: actual.VersionConflictError,
  };
});

vi.mock("../hooks/useNow", () => ({
  useNow: () => Date.now(),
}));

import { getTicket, addComment, resolveTicket, updateTicketStatus, reassignTicket, VersionConflictError } from "../api/client";

const mockGetTicket = vi.mocked(getTicket);
const mockAddComment = vi.mocked(addComment);
const mockResolveTicket = vi.mocked(resolveTicket);
const mockUpdateTicketStatus = vi.mocked(updateTicketStatus);
const mockReassignTicket = vi.mocked(reassignTicket);

// ── Test data ─────────────────────────────────────────────────────

function buildDetail(overrides: Partial<TicketDetailData["meta"]> = {}): TicketDetailData {
  return {
    meta: {
      ticket_id: "INC-001",
      title: "Caída total del sistema de pagos",
      service: "Pagos",
      description: "El gateway de pagos no responde desde las 10:00.",
      severity: "P0",
      status: "OPEN",
      assignee: "Ana López",
      sla_deadline: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
      created_at: "2026-06-03T10:00:00Z",
      updated_at: "2026-06-03T10:05:00Z",
      version: 1,
      attachments_count: 1,
      ...overrides,
    },
    events: [
      { event_type: "CREATED", actor: "system", action: "Ticket created", created_at: "2026-06-03T10:00:00Z" },
      { event_type: "ACK", actor: "Carlos Ruiz", action: "Acknowledged", created_at: "2026-06-03T10:05:00Z" },
    ],
    comments: [
      { author: "Carlos Ruiz", body: "Estoy revisando los logs.", created_at: "2026-06-03T10:10:00Z" },
    ],
    attachments: [{ filename: "captura-error.png", size: 204800 }],
  };
}

// ── Render helper ─────────────────────────────────────────────────

function renderTicketDetail(ticketId = "INC-001") {
  return render(
    <MemoryRouter initialEntries={[`/ticket/${ticketId}`]}>
      <Routes>
        <Route path="/ticket/:id" element={<TicketDetail />} />
        <Route path="/dashboard" element={<div>Dashboard mock</div>} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Render: header / timeline / side panel ────────────────────────

describe("TicketDetail — render with mock data", () => {
  it("shows a loading state, then the ticket header", async () => {
    mockGetTicket.mockResolvedValue(buildDetail());
    renderTicketDetail();

    expect(screen.getByRole("status", { name: /cargando ticket/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Caída total del sistema de pagos")).toBeInTheDocument();
    });

    expect(screen.getByText("INC-001")).toBeInTheDocument();
    // Severity/Status are rendered both in the header and the side info panel —
    // assert at least one instance of each is present.
    expect(screen.getAllByRole("status", { name: /severidad P0/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("status", { name: /estado: OPEN/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Pagos").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Ana López").length).toBeGreaterThan(0);
  });

  it("renders the merged timeline (events + comments) in chronological order", async () => {
    mockGetTicket.mockResolvedValue(buildDetail());
    renderTicketDetail();

    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    const list = screen.getByRole("list", { name: /cronología/i });
    const items = list.querySelectorAll("li");
    // 2 events + 1 comment = 3 entries
    expect(items).toHaveLength(3);

    // Chronological ascending: CREATED (10:00) → ACK (10:05) → comment (10:10)
    expect(items[0]).toHaveTextContent("Ticket creado");
    expect(items[1]).toHaveTextContent("Reconocido (ACK)");
    expect(items[2]).toHaveTextContent("Estoy revisando los logs.");
  });

  it("renders the side panel with info, attachments, and counts", async () => {
    mockGetTicket.mockResolvedValue(buildDetail());
    renderTicketDetail();

    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    expect(screen.getByText("v1")).toBeInTheDocument();
    expect(screen.getByText("captura-error.png")).toBeInTheDocument();
    expect(screen.getByText(/200\.0 KB/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /volver al dashboard/i })).toBeInTheDocument();
  });

  it("shows a not-found state when the API responds with a 404-style error", async () => {
    mockGetTicket.mockRejectedValue(new Error("Ticket not found"));
    renderTicketDetail("INC-404");

    await waitFor(() => {
      expect(screen.getByText(/ticket no encontrado/i)).toBeInTheDocument();
    });
  });

  it("shows an error state when the API fails for a non-404 reason", async () => {
    mockGetTicket.mockRejectedValue(new Error("Error de red"));
    renderTicketDetail();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Error de red");
    });
  });
});

// ── Comment flow ───────────────────────────────────────────────────

describe("TicketDetail — adding a comment", () => {
  it("submits a comment, clears the field, and shows a success message", async () => {
    const user = userEvent.setup({ delay: null });
    mockGetTicket.mockResolvedValue(buildDetail());
    mockAddComment.mockResolvedValue(undefined);

    renderTicketDetail();
    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    const authorInput = screen.getByLabelText(/tu nombre/i);
    const bodyInput = screen.getByLabelText(/^comentario$/i);

    await user.type(authorInput, "Pedro Gómez");
    await user.type(bodyInput, "Aplicando el rollback ahora mismo.");
    await user.click(screen.getByRole("button", { name: /publicar comentario/i }));

    await waitFor(() => {
      expect(mockAddComment).toHaveBeenCalledWith("INC-001", {
        author: "Pedro Gómez",
        body: "Aplicando el rollback ahora mismo.",
      });
    });

    await waitFor(() => {
      expect(screen.getByText(/comentario publicado/i)).toBeInTheDocument();
    });
    expect((bodyInput as HTMLTextAreaElement).value).toBe("");
  });

  it("shows an error message when the comment submission fails", async () => {
    const user = userEvent.setup({ delay: null });
    mockGetTicket.mockResolvedValue(buildDetail());
    mockAddComment.mockRejectedValue(new Error("No se pudo publicar"));

    renderTicketDetail();
    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    await user.type(screen.getByLabelText(/tu nombre/i), "Pedro Gómez");
    await user.type(screen.getByLabelText(/^comentario$/i), "Intento de comentario");
    await user.click(screen.getByRole("button", { name: /publicar comentario/i }));

    await waitFor(() => {
      expect(screen.getByText(/no se pudo publicar/i)).toBeInTheDocument();
    });
  });
});

// ── Resolve flow ───────────────────────────────────────────────────

describe("TicketDetail — resolving a ticket", () => {
  it("resolves successfully and reflects RESOLVED + disables the button", async () => {
    const user = userEvent.setup({ delay: null });
    mockGetTicket.mockResolvedValue(buildDetail({ status: "OPEN", version: 1 }));
    mockResolveTicket.mockResolvedValue({ status: "RESOLVED", version: 2 });

    renderTicketDetail();
    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    const resolveBtn = screen.getByRole("button", { name: /^resolver ticket$/i });
    await user.click(resolveBtn);

    await waitFor(() => {
      expect(mockResolveTicket).toHaveBeenCalledWith("INC-001", {
        actor: expect.any(String),
        version: 1,
      });
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /ticket resuelto/i })).toBeDisabled();
    });

    // StatusChip reflects the new RESOLVED status (header + side panel)
    expect(screen.getAllByRole("status", { name: /estado: RESOLVED/i }).length).toBeGreaterThan(0);
    // SLA is "frozen" — countdown replaced by the resolved indicator
    expect(screen.getByText(/resuelto antes del límite/i)).toBeInTheDocument();
  });

  it("on 409 conflict, shows a notice and refetches the ticket", async () => {
    const user = userEvent.setup({ delay: null });
    const initial = buildDetail({ status: "OPEN", version: 1 });
    const refreshed = buildDetail({ status: "ACK", version: 2 });

    mockGetTicket.mockResolvedValueOnce(initial).mockResolvedValueOnce(refreshed);
    mockResolveTicket.mockRejectedValue(new VersionConflictError());

    renderTicketDetail();
    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    await user.click(screen.getByRole("button", { name: /^resolver ticket$/i }));

    await waitFor(() => {
      expect(screen.getByText(/el ticket cambió de versión/i)).toBeInTheDocument();
    });

    // Refetch happened — getTicket called a second time
    await waitFor(() => {
      expect(mockGetTicket).toHaveBeenCalledTimes(2);
    });

    // Refreshed data is reflected (status now ACK) — UI did not break
    await waitFor(() => {
      expect(screen.getAllByRole("status", { name: /estado: ACK/i }).length).toBeGreaterThan(0);
    });
  });

  it("disables the resolve button when the ticket is already RESOLVED", async () => {
    mockGetTicket.mockResolvedValue(buildDetail({ status: "RESOLVED", version: 3 }));
    renderTicketDetail();

    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    expect(screen.getByRole("button", { name: /ticket resuelto/i })).toBeDisabled();
    expect(mockResolveTicket).not.toHaveBeenCalled();
  });
});

// ── ACK / Escalate transitions ─────────────────────────────────────

describe("TicketDetail — ACK transition", () => {
  it("calls updateTicketStatus with ACK and reflects the new status", async () => {
    const user = userEvent.setup({ delay: null });
    // After the transition the page refetches; the refreshed payload carries
    // the new status (and would carry the new timeline event in reality).
    mockGetTicket
      .mockResolvedValueOnce(buildDetail({ status: "OPEN", version: 1 }))
      .mockResolvedValue(buildDetail({ status: "ACK", version: 2 }));
    mockUpdateTicketStatus.mockResolvedValue({ status: "ACK", version: 2 });

    renderTicketDetail();
    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    const ackBtn = screen.getByRole("button", { name: /reconocer \(ack\)/i });
    await user.click(ackBtn);

    await waitFor(() => {
      expect(mockUpdateTicketStatus).toHaveBeenCalledWith(
        "INC-001",
        { status: "ACK", actor: expect.any(String), version: 1 }
      );
    });

    // Status chip in the side panel / header must reflect ACK
    await waitFor(() => {
      expect(screen.getAllByRole("status", { name: /estado: ACK/i }).length).toBeGreaterThan(0);
    });

    // Timeline already had an ACK event in the mock data — verify it renders
    expect(screen.getByText("Reconocido (ACK)")).toBeInTheDocument();
  });

  it("shows the ACK button as inactive (disabled) when the ticket is already ACK", async () => {
    mockGetTicket.mockResolvedValue(buildDetail({ status: "ACK", version: 2 }));
    renderTicketDetail();

    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    // The button should be present but disabled
    const ackBtn = screen.getByRole("button", { name: /reconocido/i });
    expect(ackBtn).toBeDisabled();
    expect(mockUpdateTicketStatus).not.toHaveBeenCalled();
  });

  it("on 409 during ACK transition, shows conflict notice and refetches", async () => {
    const user = userEvent.setup({ delay: null });
    const initial = buildDetail({ status: "OPEN", version: 1 });
    const refreshed = buildDetail({ status: "ESCALATED", version: 3 });

    mockGetTicket.mockResolvedValueOnce(initial).mockResolvedValueOnce(refreshed);
    mockUpdateTicketStatus.mockRejectedValue(new VersionConflictError());

    renderTicketDetail();
    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    await user.click(screen.getByRole("button", { name: /reconocer \(ack\)/i }));

    await waitFor(() => {
      expect(screen.getByText(/el ticket cambió de versión/i)).toBeInTheDocument();
    });

    // Refetch must have happened
    await waitFor(() => {
      expect(mockGetTicket).toHaveBeenCalledTimes(2);
    });

    // Refreshed data is shown
    await waitFor(() => {
      expect(screen.getAllByRole("status", { name: /estado: ESCALATED/i }).length).toBeGreaterThan(0);
    });
  });
});

describe("TicketDetail — Escalate transition", () => {
  it("calls updateTicketStatus with ESCALATED when ticket is OPEN", async () => {
    const user = userEvent.setup({ delay: null });
    mockGetTicket
      .mockResolvedValueOnce(buildDetail({ status: "OPEN", version: 1 }))
      .mockResolvedValue(buildDetail({ status: "ESCALATED", version: 2 }));
    mockUpdateTicketStatus.mockResolvedValue({ status: "ESCALATED", version: 2 });

    renderTicketDetail();
    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    const escalateBtn = screen.getByRole("button", { name: /^escalar$/i });
    await user.click(escalateBtn);

    await waitFor(() => {
      expect(mockUpdateTicketStatus).toHaveBeenCalledWith(
        "INC-001",
        { status: "ESCALATED", actor: expect.any(String), version: 1 }
      );
    });

    await waitFor(() => {
      expect(screen.getAllByRole("status", { name: /estado: ESCALATED/i }).length).toBeGreaterThan(0);
    });
  });

  it("shows the Escalar button as inactive (disabled) when ticket is already ESCALATED", async () => {
    mockGetTicket.mockResolvedValue(buildDetail({ status: "ESCALATED", version: 2 }));
    renderTicketDetail();

    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    const escalateBtn = screen.getByRole("button", { name: /escalado/i });
    expect(escalateBtn).toBeDisabled();
    expect(mockUpdateTicketStatus).not.toHaveBeenCalled();
  });

  it("hides ACK and Escalate buttons when the ticket is RESOLVED", async () => {
    mockGetTicket.mockResolvedValue(buildDetail({ status: "RESOLVED", version: 5 }));
    renderTicketDetail();

    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    // ACK and Escalate buttons must not be present for a terminal RESOLVED ticket
    expect(screen.queryByRole("button", { name: /reconocer/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /escalar/i })).not.toBeInTheDocument();
  });
});

// ── Attachment download link ───────────────────────────────────────

describe("TicketDetail — attachment download link", () => {
  it("renders a download anchor when the attachment has download_url", async () => {
    const detailWithUrl = buildDetail();
    detailWithUrl.attachments = [
      {
        filename: "captura-error.png",
        size: 204800,
        download_url: "https://s3.example.com/presigned/captura-error.png?token=abc",
      },
    ];
    mockGetTicket.mockResolvedValue(detailWithUrl);
    renderTicketDetail();

    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    const link = screen.getByRole("link", { name: /descargar captura-error\.png/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute(
      "href",
      "https://s3.example.com/presigned/captura-error.png?token=abc"
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("download", "captura-error.png");
  });

  it("does not render a download link when attachment has no download_url", async () => {
    const detailNoUrl = buildDetail();
    detailNoUrl.attachments = [{ filename: "captura-error.png", size: 204800 }];
    mockGetTicket.mockResolvedValue(detailNoUrl);
    renderTicketDetail();

    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    expect(
      screen.queryByRole("link", { name: /descargar captura-error\.png/i })
    ).not.toBeInTheDocument();
  });
});

// ── Reassign flow ─────────────────────────────────────────────────

describe("TicketDetail — reassigning a ticket", () => {
  it("calls reassignTicket with the correct payload, reflects the new assignee, and refetches", async () => {
    const user = userEvent.setup({ delay: null });
    const initial = buildDetail({ assignee: "Ana López", version: 1 });
    const refreshed = buildDetail({ assignee: "Pedro Gómez", version: 2 });

    mockGetTicket.mockResolvedValueOnce(initial).mockResolvedValue(refreshed);
    mockReassignTicket.mockResolvedValue({ assignee: "Pedro Gómez", version: 2 });

    renderTicketDetail();
    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    const input = screen.getByLabelText(/nuevo responsable/i);
    await user.type(input, "Pedro Gómez");
    await user.click(screen.getByRole("button", { name: /^reasignar$/i }));

    await waitFor(() => {
      expect(mockReassignTicket).toHaveBeenCalledWith(
        "INC-001",
        { assignee: "Pedro Gómez", actor: expect.any(String), version: 1 }
      );
    });

    // Refetch was triggered — getTicket called a second time
    await waitFor(() => {
      expect(mockGetTicket).toHaveBeenCalledTimes(2);
    });

    // New assignee is reflected in the UI (refreshed data from the second getTicket call)
    await waitFor(() => {
      expect(screen.getAllByText("Pedro Gómez").length).toBeGreaterThan(0);
    });
  });

  it("on 409 conflict, shows the conflict notice and refetches", async () => {
    const user = userEvent.setup({ delay: null });
    const initial = buildDetail({ assignee: "Ana López", version: 1 });
    const refreshed = buildDetail({ assignee: "Carlos Ruiz", version: 3 });

    mockGetTicket.mockResolvedValueOnce(initial).mockResolvedValue(refreshed);
    mockReassignTicket.mockRejectedValue(new VersionConflictError());

    renderTicketDetail();
    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    const input = screen.getByLabelText(/nuevo responsable/i);
    await user.type(input, "Nuevo Ingeniero");
    await user.click(screen.getByRole("button", { name: /^reasignar$/i }));

    await waitFor(() => {
      expect(screen.getByText(/el ticket cambió de versión/i)).toBeInTheDocument();
    });

    // Refetch happened
    await waitFor(() => {
      expect(mockGetTicket).toHaveBeenCalledTimes(2);
    });
  });

  it("disables the reassign button when the ticket is RESOLVED", async () => {
    mockGetTicket.mockResolvedValue(buildDetail({ status: "RESOLVED", version: 3 }));
    renderTicketDetail();

    await waitFor(() => screen.getByText("Caída total del sistema de pagos"));

    expect(screen.getByRole("button", { name: /^reasignar$/i })).toBeDisabled();
    expect(mockReassignTicket).not.toHaveBeenCalled();
  });
});
