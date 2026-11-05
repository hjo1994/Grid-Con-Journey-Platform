import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";
import { BY_STATUS, BY_TECH, CUSTOMERS, GRONOS_PAGE, PAGE, STATUSES } from "./test/fixtures";

type Responder = (url: URL) => { status: number; body?: unknown };

function mockFetch(responder: Responder) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    const { status, body } = responder(url);
    return new Response(JSON.stringify(body ?? {}), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const ok: Responder = (url) => {
  const p = url.pathname;
  if (p.endsWith("/request-statuses")) return { status: 200, body: STATUSES };
  if (p.endsWith("/grid-connection-customers")) return { status: 200, body: { items: CUSTOMERS, total: 2, limit: 500, offset: 0 } };
  if (p.endsWith("/aggregate")) return { status: 200, body: url.searchParams.get("group_by") === "request_status" ? BY_STATUS : BY_TECH };
  if (p.endsWith("/grid-connection-requests")) return { status: 200, body: PAGE };
  return { status: 404 };
};

// without a hash the app opens "Meine Bewertungen"; these tests cover the overview
beforeEach(() => {
  window.location.hash = "#/";
});
afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("shows the list with customer names and the first request in the detail panel", async () => {
    mockFetch(ok);
    render(<App />);
    expect(await screen.findByRole("cell", { name: "Unternehmen-B" })).toBeInTheDocument();

    const detail = screen.getByRole("complementary", { name: "Details zur Anfrage" });
    expect(within(detail).getByRole("heading", { name: "Projekt-1" })).toBeInTheDocument();
    expect(within(detail).getByText("Schritt 2 von 4")).toBeInTheDocument();
    expect(within(detail).getByText("Person-A")).toBeInTheDocument();
    expect(within(detail).getAllByText("nicht gepflegt")).toHaveLength(1); // Standort
    expect(within(detail).getByText("nicht konfiguriert")).toBeInTheDocument(); // no C4C URL in tests
  });

  it("selects another request on click", async () => {
    mockFetch(ok);
    render(<App />);
    await userEvent.click(await screen.findByRole("cell", { name: "Projekt-2" }));
    const detail = screen.getByRole("complementary", { name: "Details zur Anfrage" });
    expect(within(detail).getByText("Kein Prozessschritt, Anfrage liegt außerhalb des Prozesses")).toBeInTheDocument();
  });

  it("asks the backend for the two widgets as agreed", async () => {
    const fetch = mockFetch(ok);
    render(<App />);
    expect(await screen.findByText("Status der Anfragen")).toBeInTheDocument();
    const urls = fetch.mock.calls.map(([u]) => decodeURIComponent(String(u)));
    expect(urls).toContain("/api/v1/grid-connection-requests/aggregate?group_by=request_status");
    expect(urls).toContain("/api/v1/grid-connection-requests/aggregate?group_by=generation_technology&exclude_status=Eingestellt&split_multi=true");
    expect(screen.getByText("Neuer Status")).toBeInTheDocument();
  });

  it("sends search and sort to the backend", async () => {
    const fetch = mockFetch(ok);
    render(<App />);
    await screen.findByRole("cell", { name: "Projekt-1" });

    await userEvent.type(screen.getByRole("searchbox", { name: "Suche" }), "Projekt-2");
    await waitFor(() => expect(fetch.mock.calls.some(([u]) => String(u).includes("q=Projekt-2"))).toBe(true));

    await userEvent.click(screen.getByRole("button", { name: "MW" }));
    await waitFor(() => expect(fetch.mock.calls.some(([u]) => /sort=max_p&order=desc/.test(String(u)))).toBe(true));
  });

  it("shows the GRONOS API columns for API requests", async () => {
    mockFetch((url) => (url.pathname.endsWith("/grid-connection-requests") ? { status: 200, body: GRONOS_PAGE } : ok(url)));
    render(<App />);
    const detail = await screen.findByRole("complementary", { name: "Details zur Anfrage" });
    await within(detail).findByText("Verfahren in GRONOS");
    expect(within(detail).getByText("Z01")).toBeInTheDocument();
    expect(within(detail).getByText("Ja")).toBeInTheDocument();
    expect(within(detail).getByText("01.01.2027")).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: /54,0594° N, 12,3322° O/ })).toHaveAttribute(
      "href",
      expect.stringContaining("openstreetmap.org/?mlat=54.0594&mlon=12.3322"),
    );
    expect(within(detail).getByRole("list", { name: "Dokumente in GRONOS" })).toHaveTextContent("lageplan.pdfvollmacht.pdf");
    expect(within(detail).getByText("1000001")).toBeInTheDocument();
    expect(within(detail).getByText("DE000000000")).toBeInTheDocument();
    expect(within(detail).getByText("ABCDEF0123456789ABCDEF0123456789")).toBeInTheDocument();
  });

  it("hides the GRONOS rows for requests from the Excel import", async () => {
    mockFetch(ok);
    render(<App />);
    const detail = await screen.findByRole("complementary", { name: "Details zur Anfrage" });
    await within(detail).findByText("Person-A");
    expect(within(detail).queryByText("Verfahren in GRONOS")).not.toBeInTheDocument();
    expect(within(detail).queryByText("Inbetriebnahme")).not.toBeInTheDocument();
  });

  it("names the problem when the database is unavailable", async () => {
    mockFetch(() => ({ status: 503 }));
    render(<App />);
    const alerts = await screen.findAllByRole("alert");
    expect(alerts[0]).toHaveTextContent("Die Datenbank ist gerade nicht verfügbar");
  });

  it("says so when there are no users to pick", async () => {
    window.location.hash = "#/meine-bewertungen";
    mockFetch((url) => (url.pathname.endsWith("/users") ? { status: 200, body: [] } : ok(url)));
    render(<App />);
    expect(await screen.findByText(/Keine Nutzer:innen in der Datenbank/)).toBeInTheDocument();
  });

  it("names the error when the users cannot be loaded", async () => {
    window.location.hash = "#/meine-bewertungen";
    mockFetch((url) => (url.pathname.endsWith("/users") ? { status: 404 } : ok(url)));
    render(<App />);
    expect(await screen.findByText(/Nutzer:innen konnten nicht geladen werden/)).toBeInTheDocument();
  });
});
