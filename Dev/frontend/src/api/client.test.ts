import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  createTicket,
  listDashboard,
  getTicket,
  addComment,
  resolveTicket,
  updateTicketStatus,
  reassignTicket,
  VersionConflictError,
} from "./client";
import type {
  CreateTicketInput,
  DashboardItem,
  CreateTicketResponse,
  TicketDetail,
} from "../types";

// ── Helpers ──────────────────────────────────────────────────────

function mockFetch(response: unknown, ok = true, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status,
      json: () => Promise.resolve(response),
    })
  );
}

function mockFetchError(error: Error): void {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(error));
}

// ── createTicket ──────────────────────────────────────────────────

describe("createTicket", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("returns CreateTicketResponse on 201 OK", async () => {
    const payload: CreateTicketResponse = {
      ticket_id: "INC-001",
      status: "OPEN",
      sla_deadline: "2026-06-03T12:00:00Z",
    };
    mockFetch(payload, true, 201);

    const input: CreateTicketInput = {
      title: "Caída de pagos",
      service: "Pagos",
      description: "No responde el gateway",
      severity: "P0",
    };
    const result = await createTicket(input);
    expect(result.ticket_id).toBe("INC-001");
    expect(result.status).toBe("OPEN");
  });

  it("calls fetch with correct URL and method", async () => {
    const payload: CreateTicketResponse = {
      ticket_id: "INC-002",
      status: "OPEN",
      sla_deadline: "2026-06-03T12:00:00Z",
    };
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve(payload),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const input: CreateTicketInput = {
      title: "Test",
      service: "ERP",
      description: "Desc",
    };
    await createTicket(input);

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/incidents");
    expect(options.method).toBe("POST");
    expect(options.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(options.body as string)).toMatchObject({ title: "Test" });
  });

  it("throws with server error message when res.ok is false", async () => {
    mockFetch({ error: "Validation failed" }, false, 422);
    const input: CreateTicketInput = {
      title: "x",
      service: "ERP",
      description: "y",
    };
    await expect(createTicket(input)).rejects.toThrow("Validation failed");
  });

  it("throws HTTP status when response body has no error field", async () => {
    mockFetch({}, false, 500);
    const input: CreateTicketInput = {
      title: "x",
      service: "ERP",
      description: "y",
    };
    await expect(createTicket(input)).rejects.toThrow("HTTP 500");
  });

  it("propagates network errors", async () => {
    mockFetchError(new Error("Network failure"));
    const input: CreateTicketInput = {
      title: "x",
      service: "ERP",
      description: "y",
    };
    await expect(createTicket(input)).rejects.toThrow("Network failure");
  });
});

// ── listDashboard ─────────────────────────────────────────────────

describe("listDashboard", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  const mockItems: DashboardItem[] = [
    {
      ticket_id: "INC-001",
      severity: "P0",
      status: "OPEN",
      title: "Caída pagos",
      service: "Pagos",
      assignee: "Ana López",
      sla_deadline: "2026-06-03T12:00:00Z",
    },
  ];

  it("returns items array on successful response", async () => {
    mockFetch({ items: mockItems });
    const result = await listDashboard("ana.lopez", "OPEN");
    expect(result).toHaveLength(1);
    expect(result[0].ticket_id).toBe("INC-001");
  });

  it("builds query string with assignee and status", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ items: [] }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    await listDashboard("maria.garcia", "ESCALATED");

    const [url] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("assignee=maria.garcia");
    expect(url).toContain("status=ESCALATED");
  });

  it("throws on non-ok response", async () => {
    mockFetch({ message: "Unauthorized" }, false, 401);
    await expect(listDashboard("x", "OPEN")).rejects.toThrow("Unauthorized");
  });

  it("omits the assignee param when assignee is empty (all-mode)", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ items: [] }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    await listDashboard("", "OPEN");

    const [url] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("status=OPEN");
    expect(url).not.toContain("assignee");
  });

  it("omits the assignee param when assignee is whitespace-only", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ items: [] }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    await listDashboard("   ", "OPEN");

    const [url] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).not.toContain("assignee");
  });

  it("passes AbortSignal to fetch", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ items: [] }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const controller = new AbortController();
    await listDashboard("user", "OPEN", controller.signal);

    const [, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(options.signal).toBe(controller.signal);
  });
});

// ── getTicket ─────────────────────────────────────────────────────

describe("getTicket", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  const mockDetail: TicketDetail = {
    meta: {
      ticket_id: "INC-001",
      title: "Caída de pagos",
      service: "Pagos",
      description: "El gateway no responde",
      severity: "P0",
      status: "OPEN",
      assignee: "Ana López",
      sla_deadline: "2026-06-03T12:00:00Z",
      created_at: "2026-06-03T11:00:00Z",
      updated_at: "2026-06-03T11:05:00Z",
      version: 1,
      attachments_count: 0,
    },
    events: [{ event_type: "CREATED", actor: "system", action: "Ticket created", created_at: "2026-06-03T11:00:00Z" }],
    comments: [],
    attachments: [],
  };

  it("returns the assembled TicketDetail on 200 OK", async () => {
    mockFetch(mockDetail);
    const result = await getTicket("INC-001");
    expect(result.meta.ticket_id).toBe("INC-001");
    expect(result.events).toHaveLength(1);
  });

  it("calls fetch with the correct URL and AbortSignal", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockDetail),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const controller = new AbortController();
    await getTicket("INC-001", controller.signal);

    const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/incidents/INC-001");
    expect(options.signal).toBe(controller.signal);
  });

  it("throws with server error message on non-ok response", async () => {
    mockFetch({ error: "Ticket no encontrado" }, false, 404);
    await expect(getTicket("INC-404")).rejects.toThrow("Ticket no encontrado");
  });
});

// ── addComment ────────────────────────────────────────────────────

describe("addComment", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("posts to the comments endpoint with author and body", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    await addComment("INC-001", { author: "Ana López", body: "Investigando la causa raíz" });

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/incidents/INC-001/comments");
    expect(options.method).toBe("POST");
    expect(options.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(options.body as string)).toEqual({
      author: "Ana López",
      body: "Investigando la causa raíz",
    });
  });

  it("throws with server error message on non-ok response", async () => {
    mockFetch({ error: "Validación fallida" }, false, 400);
    await expect(addComment("INC-001", { author: "x", body: "y" })).rejects.toThrow(
      "Validación fallida"
    );
  });
});

// ── resolveTicket ─────────────────────────────────────────────────

describe("resolveTicket", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("PATCHes status RESOLVED with actor and version, returns the new state", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ status: "RESOLVED", version: 2 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const result = await resolveTicket("INC-001", { actor: "Ana López", version: 1 });

    expect(result).toEqual({ status: "RESOLVED", version: 2 });
    const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/incidents/INC-001");
    expect(options.method).toBe("PATCH");
    expect(JSON.parse(options.body as string)).toEqual({
      status: "RESOLVED",
      actor: "Ana López",
      version: 1,
    });
  });

  it("throws a VersionConflictError on 409 (optimistic concurrency conflict)", async () => {
    mockFetch({ error: "Version mismatch" }, false, 409);

    await expect(resolveTicket("INC-001", { actor: "Ana López", version: 1 })).rejects.toThrow(
      VersionConflictError
    );

    // Distinguishable via the `isVersionConflict` flag too — not just instanceof
    try {
      await resolveTicket("INC-001", { actor: "Ana López", version: 1 });
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(VersionConflictError);
      expect((err as VersionConflictError).isVersionConflict).toBe(true);
    }
  });

  it("throws a generic error with the server message on other failures (e.g. 404)", async () => {
    mockFetch({ error: "Ticket no encontrado" }, false, 404);
    await expect(
      resolveTicket("INC-404", { actor: "Ana López", version: 1 })
    ).rejects.toThrow("Ticket no encontrado");
  });
});

// ── updateTicketStatus ────────────────────────────────────────────

describe("updateTicketStatus", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("PATCHes with status ACK and returns the new state", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ status: "ACK", version: 2 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const result = await updateTicketStatus("INC-001", {
      status: "ACK",
      actor: "Ana López",
      version: 1,
    });

    expect(result).toEqual({ status: "ACK", version: 2 });
    const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/incidents/INC-001");
    expect(options.method).toBe("PATCH");
    expect(JSON.parse(options.body as string)).toEqual({
      status: "ACK",
      actor: "Ana López",
      version: 1,
    });
  });

  it("PATCHes with status ESCALATED and returns the new state", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ status: "ESCALATED", version: 3 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const result = await updateTicketStatus("INC-001", {
      status: "ESCALATED",
      actor: "Ana López",
      version: 2,
    });

    expect(result).toEqual({ status: "ESCALATED", version: 3 });
    const [, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(options.body as string)).toMatchObject({ status: "ESCALATED" });
  });

  it("throws a VersionConflictError on 409", async () => {
    mockFetch({ error: "Version mismatch" }, false, 409);

    await expect(
      updateTicketStatus("INC-001", { status: "ACK", actor: "Ana López", version: 1 })
    ).rejects.toThrow(VersionConflictError);

    try {
      await updateTicketStatus("INC-001", { status: "ACK", actor: "Ana López", version: 1 });
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(VersionConflictError);
      expect((err as VersionConflictError).isVersionConflict).toBe(true);
    }
  });

  it("throws a generic error with server message on 400 (invalid transition)", async () => {
    mockFetch({ error: "Transición no permitida" }, false, 400);
    await expect(
      updateTicketStatus("INC-001", { status: "ACK", actor: "Ana López", version: 1 })
    ).rejects.toThrow("Transición no permitida");
  });

  it("passes AbortSignal to fetch", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ status: "ACK", version: 2 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const controller = new AbortController();
    await updateTicketStatus("INC-001", { status: "ACK", actor: "Ana López", version: 1 }, controller.signal);

    const [, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(options.signal).toBe(controller.signal);
  });
});

// ── reassignTicket ────────────────────────────────────────────────

describe("reassignTicket", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("PATCHes the assignee endpoint and returns the updated assignee and version", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ assignee: "Pedro Gómez", version: 2 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const result = await reassignTicket("INC-001", {
      assignee: "Pedro Gómez",
      actor: "Ana López",
      version: 1,
    });

    expect(result).toEqual({ assignee: "Pedro Gómez", version: 2 });

    const [url, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/incidents/INC-001/assignee");
    expect(options.method).toBe("PATCH");
    expect(options.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(options.body as string)).toEqual({
      assignee: "Pedro Gómez",
      actor: "Ana López",
      version: 1,
    });
  });

  it("throws a VersionConflictError on 409 (optimistic concurrency conflict)", async () => {
    mockFetch({ error: "Version mismatch" }, false, 409);

    await expect(
      reassignTicket("INC-001", { assignee: "Pedro Gómez", actor: "Ana López", version: 1 })
    ).rejects.toThrow(VersionConflictError);

    try {
      await reassignTicket("INC-001", { assignee: "Pedro Gómez", actor: "Ana López", version: 1 });
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(VersionConflictError);
      expect((err as VersionConflictError).isVersionConflict).toBe(true);
    }
  });

  it("throws a generic error on 400 (e.g. ticket is RESOLVED or missing fields)", async () => {
    mockFetch({ error: "No se puede reasignar un ticket resuelto" }, false, 400);
    await expect(
      reassignTicket("INC-001", { assignee: "Pedro Gómez", actor: "Ana López", version: 3 })
    ).rejects.toThrow("No se puede reasignar un ticket resuelto");
  });

  it("passes AbortSignal to fetch", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ assignee: "Pedro Gómez", version: 2 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const controller = new AbortController();
    await reassignTicket(
      "INC-001",
      { assignee: "Pedro Gómez", actor: "Ana López", version: 1 },
      controller.signal
    );

    const [, options] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(options.signal).toBe(controller.signal);
  });
});
