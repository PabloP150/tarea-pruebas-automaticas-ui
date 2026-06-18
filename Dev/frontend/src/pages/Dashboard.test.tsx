import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// ── Navigation spy — mock useNavigate while keeping the rest of the module ──

const navigateSpy = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  };
});
import Dashboard from "./Dashboard";
import type { DashboardItem } from "../types";

// ── Module mock for api/client ────────────────────────────────────

vi.mock("../api/client", () => ({
  listDashboard: vi.fn(),
}));

// Provide a no-op NowProvider so SlaCountdown gets a stable context value
vi.mock("../providers/NowProvider", () => ({
  NowProvider: ({ children }: { children: React.ReactNode }) => children,
  NowContext: { _currentValue: Date.now() },
}));

vi.mock("../hooks/useNow", () => ({
  useNow: () => Date.now(),
}));

import { listDashboard } from "../api/client";

const mockListDashboard = vi.mocked(listDashboard);

// ── Test data ─────────────────────────────────────────────────────

const MOCK_ITEMS: DashboardItem[] = [
  {
    ticket_id: "INC-001",
    severity: "P0",
    status: "OPEN",
    title: "Caída total del sistema de pagos",
    service: "Pagos",
    assignee: "Ana López",
    sla_deadline: new Date(Date.now() + 10 * 60 * 1000).toISOString(), // +10 min
  },
  {
    ticket_id: "INC-002",
    severity: "P1",
    status: "ACK",
    title: "ERP lento en horario pico",
    service: "ERP",
    assignee: "Carlos Ruiz",
    sla_deadline: new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString(), // +3h
  },
  {
    ticket_id: "INC-003",
    severity: "P2",
    status: "OPEN",
    title: "Impresoras sin conectividad",
    service: "Impresoras",
    assignee: "Ana López",
    sla_deadline: new Date(Date.now() + 20 * 60 * 60 * 1000).toISOString(), // +20h
  },
];

// ── Render helper ─────────────────────────────────────────────────

function renderDashboard() {
  return render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>
  );
}

// ── Render — no assignee (all-mode) ──────────────────────────────

describe("Dashboard — no assignee (all-mode)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("fires listDashboard immediately with no assignee param (all-mode)", async () => {
    // Mock returns empty so we reach stable state quickly
    mockListDashboard.mockResolvedValue([]);
    renderDashboard();
    // listDashboard should be called on mount even without an assignee
    await waitFor(() => {
      expect(mockListDashboard).toHaveBeenCalled();
    });
  });

  it("shows the all-mode subtitle when no assignee is set", async () => {
    mockListDashboard.mockResolvedValue([]);
    renderDashboard();
    // The subtitle paragraph communicates all-pending mode
    const subtitle = screen.getByText(/mostrando/i);
    expect(subtitle).toBeInTheDocument();
    expect(subtitle.textContent).toMatch(/todos los pendientes/i);
  });

  it("shows stat cards with zero values when results are empty", async () => {
    mockListDashboard.mockResolvedValue([]);
    renderDashboard();
    await waitFor(() => expect(mockListDashboard).toHaveBeenCalled());
    // All stat values should show 0
    const statValues = screen.getAllByText("0");
    expect(statValues.length).toBeGreaterThanOrEqual(4);
  });
});

// ── Render — with data ────────────────────────────────────────────

describe("Dashboard — renders rows with mock data", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("renders ticket rows after entering an assignee", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue(MOCK_ITEMS);

    renderDashboard();

    const input = screen.getByLabelText(/ingeniero/i);
    await user.type(input, "Ana López");

    await waitFor(
      () => {
        expect(screen.getByText("INC-001")).toBeInTheDocument();
      },
      { timeout: 3000 }
    );

    expect(screen.getByText("INC-002")).toBeInTheDocument();
    expect(screen.getByText("INC-003")).toBeInTheDocument();
  });

  it("renders correct severity badges", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue(MOCK_ITEMS);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByText("INC-001"), { timeout: 3000 });

    // SeverityBadge renders abbreviated level (P0, P1, P2)
    expect(screen.getByRole("status", { name: /severidad P0/i })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: /severidad P1/i })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: /severidad P2/i })).toBeInTheDocument();
  });

  it("renders correct status chips", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue(MOCK_ITEMS);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByText("INC-001"), { timeout: 3000 });

    // Two items have OPEN status (INC-001 and INC-003), one has ACK (INC-002)
    const openChips = screen.getAllByRole("status", { name: /estado: OPEN/i });
    expect(openChips.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("status", { name: /estado: ACK/i })).toBeInTheDocument();
  });

  it("stat cards reflect loaded data counts", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue(MOCK_ITEMS);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByText("INC-001"), { timeout: 3000 });

    // Total = 3
    expect(screen.getByLabelText(/total: 3 tickets/i)).toBeInTheDocument();
    // P0 count = 1
    expect(screen.getByLabelText(/p0 crítico: 1 tickets/i)).toBeInTheDocument();
    // P1 count = 1
    expect(screen.getByLabelText(/p1 alto: 1 tickets/i)).toBeInTheDocument();
    // P2 count = 1
    expect(screen.getByLabelText(/p2 normal: 1 tickets/i)).toBeInTheDocument();
  });
});

// ── Loading state ─────────────────────────────────────────────────

describe("Dashboard — loading state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("shows skeleton during initial load (all-mode)", async () => {
    // Never resolve — keeps loading state indefinitely
    mockListDashboard.mockReturnValue(new Promise(() => {}));

    renderDashboard();

    // Skeleton should appear immediately on mount (all-mode fires fetch right away)
    await waitFor(() => {
      expect(screen.getByRole("status", { name: /cargando tickets/i })).toBeInTheDocument();
    });
  });
});

// ── Error state ───────────────────────────────────────────────────

describe("Dashboard — error state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("shows error message when API rejects", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockRejectedValue(new Error("Error de conexión"));

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(
      () => {
        expect(screen.getByRole("alert")).toHaveTextContent("Error de conexión");
      },
      { timeout: 3000 }
    );
  });
});

// ── Empty results ─────────────────────────────────────────────────

describe("Dashboard — empty results", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("shows empty state when API returns no tickets", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue([]);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Pedro Sin Tickets");

    await waitFor(
      () => {
        expect(screen.getByText(/sin tickets pendientes/i)).toBeInTheDocument();
      },
      { timeout: 3000 }
    );
  });
});

// ── localStorage persistence ──────────────────────────────────────

describe("Dashboard — assignee localStorage persistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("reads assignee from localStorage on mount", () => {
    // Set BEFORE clearing so the value is present when Dashboard initializes
    localStorage.clear();
    localStorage.setItem("ticketresolve_assignee", "Maria García");
    mockListDashboard.mockResolvedValue([]);

    renderDashboard();

    const input = screen.getByLabelText(/ingeniero/i) as HTMLInputElement;
    expect(input.value).toBe("Maria García");
  });

  it("persists new assignee to localStorage after debounce", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue([]);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Nuevo Ingeniero");

    await waitFor(
      () => {
        expect(localStorage.getItem("ticketresolve_assignee")).toBe("Nuevo Ingeniero");
      },
      { timeout: 2000 }
    );
  });
});

// ── isRefreshing vs isLoading distinction ─────────────────────────

describe("Dashboard — isRefreshing vs isLoading", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("shows table rows while refreshing (not skeleton)", async () => {
    const user = userEvent.setup({ delay: null });

    // All-mode fetch on mount resolves with empty (no data yet)
    mockListDashboard.mockResolvedValueOnce([]);
    // Fetch after typing "Ana López" resolves with data
    mockListDashboard.mockResolvedValueOnce(MOCK_ITEMS);
    // Manual refresh call stays pending — allows us to assert busy state
    mockListDashboard.mockReturnValueOnce(new Promise(() => {}));

    renderDashboard();

    // Wait for all-mode mount fetch to settle (empty state)
    await waitFor(() => expect(mockListDashboard).toHaveBeenCalledTimes(1));

    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    // Wait for table to render after typing
    await waitFor(() => screen.getByText("INC-001"), { timeout: 3000 });

    // Click manual refresh
    const refreshBtn = screen.getByRole("button", { name: /refrescar datos/i });
    await user.click(refreshBtn);

    // Table rows must still be visible (not replaced by skeleton)
    expect(screen.getByText("INC-001")).toBeInTheDocument();

    // Skeleton must NOT be present
    const skeletonTable = document.querySelector(".skeleton-table");
    expect(skeletonTable).toBeNull();

    // The table panel should indicate busy state
    const tableRegion = screen.getByRole("region", { name: /tickets de ana/i });
    expect(tableRegion).toHaveAttribute("aria-busy", "true");
  });
});

// ── SlaCountdown cells ────────────────────────────────────────────

describe("Dashboard — SlaCountdown in table rows", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("renders SLA countdown timers for each row", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue(MOCK_ITEMS);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByText("INC-001"), { timeout: 3000 });

    const timers = screen.getAllByRole("timer");
    expect(timers).toHaveLength(MOCK_ITEMS.length);
  });

  it("marks expired SLA as 'vencido'", async () => {
    const user = userEvent.setup({ delay: null });
    const expiredItem: DashboardItem = {
      ...MOCK_ITEMS[0],
      ticket_id: "INC-EXP",
      sla_deadline: new Date(Date.now() - 5 * 60 * 1000).toISOString(), // -5 min
    };
    mockListDashboard.mockResolvedValue([expiredItem]);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByRole("timer"), { timeout: 3000 });

    // Scope to the timer — the dashboard also shows a "SLA vencido" alert
    // pill in the header, so a page-wide /vencido/i query would be ambiguous.
    const timer = screen.getByRole("timer");
    expect(within(timer).getByText("vencido")).toBeInTheDocument();
    expect(timer).toHaveAttribute("aria-label", "SLA vencido");
  });

  it("shows the breached-SLA alert pill in the header when a ticket is past due", async () => {
    const user = userEvent.setup({ delay: null });
    const expiredItem: DashboardItem = {
      ...MOCK_ITEMS[0],
      ticket_id: "INC-EXP",
      sla_deadline: new Date(Date.now() - 5 * 60 * 1000).toISOString(), // -5 min
    };
    mockListDashboard.mockResolvedValue([expiredItem]);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByRole("timer"), { timeout: 3000 });

    // The alert pill announces the count of breached-SLA tickets distinctly
    // from the per-row countdown's own "vencido" label.
    expect(
      screen.getByText((_, node) => node?.textContent === "1 ticket con SLA vencido")
    ).toBeInTheDocument();
  });
});

// ── Client-side severity filter (stat-card click) ─────────────────

describe("Dashboard — severity filter via stat-card", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("filters table rows to a single severity when its stat-card is clicked, and clears on second click", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue(MOCK_ITEMS);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByText("INC-001"), { timeout: 3000 });

    // All three rows visible initially
    expect(screen.getByText("INC-001")).toBeInTheDocument();
    expect(screen.getByText("INC-002")).toBeInTheDocument();
    expect(screen.getByText("INC-003")).toBeInTheDocument();

    // Click the P1 stat-card to filter down to P1-only rows
    const p1Card = screen.getByRole("button", { name: /^P1 Alto: 1 tickets/i });
    await user.click(p1Card);

    expect(p1Card).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("INC-002")).toBeInTheDocument();
    expect(screen.queryByText("INC-001")).not.toBeInTheDocument();
    expect(screen.queryByText("INC-003")).not.toBeInTheDocument();

    // The toolbar shows a removable filter tag for the active severity
    const clearTag = screen.getByRole("button", { name: /quitar filtro de severidad p1/i });
    expect(clearTag).toBeInTheDocument();

    // Clicking the same card again clears the filter — all rows return
    await user.click(p1Card);
    expect(p1Card).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("INC-001")).toBeInTheDocument();
    expect(screen.getByText("INC-002")).toBeInTheDocument();
    expect(screen.getByText("INC-003")).toBeInTheDocument();
  });

  it("shows an inline empty state when the active severity filter matches no rows", async () => {
    const user = userEvent.setup({ delay: null });
    // Only P1 and P2 items — no P0 in this assignee's queue
    mockListDashboard.mockResolvedValue([MOCK_ITEMS[1], MOCK_ITEMS[2]]);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByText("INC-002"), { timeout: 3000 });

    const p0Card = screen.getByRole("button", { name: /^P0 Crítico: 0 tickets/i });
    await user.click(p0Card);

    expect(screen.getByText(/ningún ticket P0 en esta vista/i)).toBeInTheDocument();
    expect(screen.queryByText("INC-002")).not.toBeInTheDocument();

    // Can clear the filter from the inline empty state too
    await user.click(screen.getByRole("button", { name: /mostrar todas las severidades/i }));
    expect(screen.getByText("INC-002")).toBeInTheDocument();
  });
});

// ── Row navigation → M3 ticket detail ─────────────────────────────

describe("Dashboard — row navigation to ticket detail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigateSpy.mockClear();
    localStorage.clear();
  });

  it("navigates to /ticket/:id when a row is clicked", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue(MOCK_ITEMS);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByText("INC-001"), { timeout: 3000 });

    const row = screen.getByRole("link", { name: /abrir ticket inc-001/i });
    await user.click(row);

    expect(navigateSpy).toHaveBeenCalledWith("/ticket/INC-001");
  });

  it("navigates with the keyboard (Enter) when a row is focused", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue(MOCK_ITEMS);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByText("INC-002"), { timeout: 3000 });

    const row = screen.getByRole("link", { name: /abrir ticket inc-002/i });
    row.focus();
    await user.keyboard("{Enter}");

    expect(navigateSpy).toHaveBeenCalledWith("/ticket/INC-002");
  });

  it("each row is keyboard-focusable and exposes an accessible link role", async () => {
    const user = userEvent.setup({ delay: null });
    mockListDashboard.mockResolvedValue(MOCK_ITEMS);

    renderDashboard();
    await user.type(screen.getByLabelText(/ingeniero/i), "Ana López");

    await waitFor(() => screen.getByText("INC-003"), { timeout: 3000 });

    const rows = screen.getAllByRole("link", { name: /abrir ticket inc-/i });
    expect(rows).toHaveLength(MOCK_ITEMS.length);
    rows.forEach((row) => {
      expect(row).toHaveAttribute("tabindex", "0");
    });
  });
});
