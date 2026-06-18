import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import CreateTicket from "./CreateTicket";

// ── Module mock for api/client ────────────────────────────────────

vi.mock("../api/client", () => ({
  createTicket: vi.fn(),
}));

import { createTicket } from "../api/client";
import type { CreateTicketResponse } from "../types";

const mockCreateTicket = vi.mocked(createTicket);

// ── Render helper ─────────────────────────────────────────────────

function renderCreateTicket() {
  return render(
    <MemoryRouter>
      <CreateTicket />
    </MemoryRouter>
  );
}

const successResponse: CreateTicketResponse = {
  ticket_id: "INC-999",
  status: "OPEN",
  sla_deadline: "2026-06-03T12:00:00Z",
};

// ── Validation ────────────────────────────────────────────────────

describe("CreateTicket — form validation", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("renders the form with required fields", () => {
    renderCreateTicket();
    expect(screen.getByLabelText(/título del incidente/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/descripción del incidente/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /emitir ticket/i })).toBeInTheDocument();
  });

  it("shows error when title is empty on submit", async () => {
    const user = userEvent.setup();
    renderCreateTicket();

    await user.click(screen.getByRole("button", { name: /emitir ticket/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/título.*requerido/i);
    expect(mockCreateTicket).not.toHaveBeenCalled();
  });

  it("shows error when description is empty on submit", async () => {
    const user = userEvent.setup();
    renderCreateTicket();

    await user.type(screen.getByLabelText(/título del incidente/i), "Caída de pagos");
    await user.click(screen.getByRole("button", { name: /emitir ticket/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/descripción.*requerida/i);
    expect(mockCreateTicket).not.toHaveBeenCalled();
  });

  it("does not call createTicket when both required fields are empty", async () => {
    const user = userEvent.setup();
    renderCreateTicket();

    await user.click(screen.getByRole("button", { name: /emitir ticket/i }));

    expect(mockCreateTicket).not.toHaveBeenCalled();
  });
});

// ── Successful submit ─────────────────────────────────────────────

describe("CreateTicket — successful submission", () => {
  beforeEach(() => vi.clearAllMocks());

  it("calls createTicket with correct payload and shows success state", async () => {
    const user = userEvent.setup();
    mockCreateTicket.mockResolvedValueOnce(successResponse);

    renderCreateTicket();

    await user.type(screen.getByLabelText(/título del incidente/i), "Caída de pagos");
    await user.type(screen.getByLabelText(/descripción del incidente/i), "No responde el gateway");
    await user.click(screen.getByRole("button", { name: /emitir ticket/i }));

    await waitFor(() => {
      expect(screen.getByText("INC-999")).toBeInTheDocument();
    });

    expect(mockCreateTicket).toHaveBeenCalledOnce();
    expect(mockCreateTicket).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Caída de pagos",
        description: "No responde el gateway",
      })
    );
  });

  it("displays ticket ID and status on success screen", async () => {
    const user = userEvent.setup();
    mockCreateTicket.mockResolvedValueOnce(successResponse);

    renderCreateTicket();

    await user.type(screen.getByLabelText(/título del incidente/i), "Test");
    await user.type(screen.getByLabelText(/descripción del incidente/i), "Test desc");
    await user.click(screen.getByRole("button", { name: /emitir ticket/i }));

    await waitFor(() => {
      expect(screen.getByText("INC-999")).toBeInTheDocument();
    });
    expect(screen.getByText("Ticket emitido correctamente")).toBeInTheDocument();
  });

  it("resets form when 'Emitir otro ticket' is clicked", async () => {
    const user = userEvent.setup();
    mockCreateTicket.mockResolvedValueOnce(successResponse);

    renderCreateTicket();

    await user.type(screen.getByLabelText(/título del incidente/i), "Test");
    await user.type(screen.getByLabelText(/descripción del incidente/i), "Test desc");
    await user.click(screen.getByRole("button", { name: /emitir ticket/i }));

    await waitFor(() => screen.getByText("Ticket emitido correctamente"));
    await user.click(screen.getByRole("button", { name: /emitir otro ticket/i }));

    // Should be back at the form
    expect(screen.getByLabelText(/título del incidente/i)).toHaveValue("");
  });
});

// ── API error handling ────────────────────────────────────────────

describe("CreateTicket — API error state", () => {
  beforeEach(() => vi.clearAllMocks());

  it("displays error message when API rejects", async () => {
    const user = userEvent.setup();
    mockCreateTicket.mockRejectedValueOnce(new Error("Servicio no disponible"));

    renderCreateTicket();

    await user.type(screen.getByLabelText(/título del incidente/i), "Caída ERP");
    await user.type(screen.getByLabelText(/descripción del incidente/i), "Timeout en BD");
    await user.click(screen.getByRole("button", { name: /emitir ticket/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Servicio no disponible");
  });

  it("re-enables submit button after error", async () => {
    const user = userEvent.setup();
    mockCreateTicket.mockRejectedValueOnce(new Error("Error interno"));

    renderCreateTicket();

    await user.type(screen.getByLabelText(/título del incidente/i), "Test");
    await user.type(screen.getByLabelText(/descripción del incidente/i), "Test");
    await user.click(screen.getByRole("button", { name: /emitir ticket/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /emitir ticket/i })).not.toBeDisabled();
    });
  });
});

// ── Attachment flow ───────────────────────────────────────────────

describe("CreateTicket — attachment flow", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends attachment metadata when a file is selected", async () => {
    const user = userEvent.setup();
    mockCreateTicket.mockResolvedValueOnce({
      ...successResponse,
      upload_url: "https://s3.example.com/presigned-url",
    });

    // Mock global fetch for the S3 PUT (not the createTicket call)
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200 })
    );

    renderCreateTicket();

    const file = new File(["log contents"], "error.log", { type: "text/plain" });
    await user.type(screen.getByLabelText(/título del incidente/i), "Caída con adjunto");
    await user.type(screen.getByLabelText(/descripción del incidente/i), "Ver adjunto");

    const fileInput = screen.getByLabelText(/seleccionar archivo adjunto/i);
    await user.upload(fileInput, file);

    await user.click(screen.getByRole("button", { name: /emitir ticket/i }));

    await waitFor(() => {
      expect(mockCreateTicket).toHaveBeenCalledWith(
        expect.objectContaining({
          attachment: { filename: "error.log", content_type: "text/plain" },
        })
      );
    });

    vi.unstubAllGlobals();
  });

  it("shows the chosen file name inside the dropzone", async () => {
    const user = userEvent.setup();
    renderCreateTicket();

    const file = new File(["log contents"], "incident-trace.log", { type: "text/plain" });
    const fileInput = screen.getByLabelText(/seleccionar archivo adjunto/i);
    await user.upload(fileInput, file);

    const dropzone = screen.getByRole("button", { name: /archivo adjunto: incident-trace\.log/i });
    expect(within(dropzone).getByText("incident-trace.log")).toBeInTheDocument();
  });
});

// ── Interactive composer controls (severity cards, service chips) ─

describe("CreateTicket — interactive composer controls", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders severity as a selectable card group defaulting to P2", () => {
    renderCreateTicket();

    const group = screen.getByRole("radiogroup", { name: /nivel de severidad del incidente/i });
    const p0 = within(group).getByRole("radio", { name: /p0/i });
    const p1 = within(group).getByRole("radio", { name: /p1/i });
    const p2 = within(group).getByRole("radio", { name: /p2/i });

    expect(p2).toHaveAttribute("aria-checked", "true");
    expect(p0).toHaveAttribute("aria-checked", "false");
    expect(p1).toHaveAttribute("aria-checked", "false");
  });

  it("updates the live preview's severity badge and SLA window when a severity card is selected", async () => {
    const user = userEvent.setup();
    renderCreateTicket();

    const preview = screen.getByLabelText(/vista previa en vivo del ticket/i);
    expect(within(preview).getByText("SLA de respuesta").nextSibling).toHaveTextContent("24 h");

    const group = screen.getByRole("radiogroup", { name: /nivel de severidad del incidente/i });
    await user.click(within(group).getByRole("radio", { name: /p0/i }));

    expect(within(group).getByRole("radio", { name: /p0/i })).toHaveAttribute("aria-checked", "true");
    expect(within(preview).getByText("SLA de respuesta").nextSibling).toHaveTextContent("15 min");
    // Severity badge inside the live preview reflects the new selection
    expect(within(preview).getAllByText("P0").length).toBeGreaterThan(0);
  });

  it("lets the user pick a service from the chip group and includes it in the submitted payload", async () => {
    const user = userEvent.setup();
    mockCreateTicket.mockResolvedValueOnce(successResponse);

    renderCreateTicket();

    const serviceGroup = screen.getByRole("radiogroup", { name: /servicio afectado/i });
    const redChip = within(serviceGroup).getByRole("radio", { name: /^red$/i });
    await user.click(redChip);
    expect(redChip).toHaveAttribute("aria-checked", "true");

    await user.type(screen.getByLabelText(/título del incidente/i), "Latencia en la red interna");
    await user.type(screen.getByLabelText(/descripción del incidente/i), "Pings intermitentes");
    await user.click(screen.getByRole("button", { name: /emitir ticket/i }));

    await waitFor(() => {
      expect(mockCreateTicket).toHaveBeenCalledWith(
        expect.objectContaining({ service: "Red" })
      );
    });
  });

  it("reflects the typed title and assignee live in the preview panel", async () => {
    const user = userEvent.setup();
    renderCreateTicket();

    const preview = screen.getByLabelText(/vista previa en vivo del ticket/i);

    await user.type(screen.getByLabelText(/título del incidente/i), "Latencia crítica en ERP");
    expect(within(preview).getByText("Latencia crítica en ERP")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/^asignado/i), "Marisol Pérez");
    expect(within(preview).getByText("Marisol Pérez")).toBeInTheDocument();
    // initials are derived live for the avatar preview
    expect(within(preview).getByText("MP")).toBeInTheDocument();
  });
});
