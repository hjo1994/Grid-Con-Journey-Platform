import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { EvaluationEntry, EvaluationState, User } from "../api/types";
import { FRAMEWORK } from "../test/fixtures";
import { EvaluationView } from "./EvaluationView";
import { HistoryView } from "./HistoryView";

const ME: User = { id: "u-np", email: "np@x", name: "J. H.", role: "netzplanung", role_label: "Netzplanung", can_evaluate: true };
const RE: User = { id: "u-re", email: "re@x", name: "A. Becker", role: "flaechen_recht", role_label: "Flächen & Recht", can_evaluate: true };
const entry = (user: string, check: string, verdict: EvaluationEntry["verdict"], score: number | null, comment: string | null = null): EvaluationEntry => ({
  id: `${user}-${check}-${verdict}`, user_id: user, evaluation_check_id: check, verdict, score, comment, version: 1, timestamp: "2026-11-03T09:12:00Z", pending: false,
});

function setup(checks: EvaluationEntry[]) {
  let current = [...checks];
  const posts: unknown[] = [];
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      posts.push({ body, user: (init.headers as Record<string, string>)["X-User-ID"] });
      for (const c of body.checks) {
        current = current.filter((e) => !(e.user_id === ME.id && e.evaluation_check_id === c.evaluation_check_id));
        current.push(entry(ME.id, c.evaluation_check_id, c.verdict, c.verdict === "fulfilled" ? 2 : 0, c.comment));
      }
      return json({ items: [] }, 201);
    }
    if (url.pathname.endsWith("/evaluation-framework")) return json(FRAMEWORK);
    if (url.pathname.endsWith("/evaluation")) {
      const state: EvaluationState = { id_gronos_new: 4902, grid_connection_request_id: "r1", evaluators: [ME, RE], checks: current, last_change: null };
      return json(state);
    }
    if (url.pathname.endsWith("/evaluation-history"))
      return json({ id_gronos_new: 4902, total: 1, items: [{ ...entry(RE.id, "B3-04", "not_fulfilled", 0, "Wegerechte fehlen"), action: "changed", previous_verdict: "fulfilled", previous_score: 2, sub_criterion_id: "B3", scoring_group: "B3" }] });
    if (url.pathname.endsWith("/4902")) return json({ id_gronos_old: "Projekt-G02", generation_technology: "Wind", max_p: 300, customer: { customer_name: "Unternehmen-101" } });
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetch);
  return posts;
}

afterEach(() => vi.unstubAllGlobals());

describe("K1 evaluation", () => {
  it("shows own column first, marks differences and the comment thread", async () => {
    setup([entry(ME.id, "B3-01", "fulfilled", 0), entry(ME.id, "B3-03", "fulfilled", 1), entry(RE.id, "B3-01", "fulfilled", 0), entry(RE.id, "B3-04", "not_fulfilled", 0)]);
    render(<EvaluationView id={4902} me={ME} />);
    expect(await screen.findByText("Einschätzungen weichen ab")).toBeInTheDocument();
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers[1]).toContain("Netzplanung");
    expect(headers[1]).toContain("du");
    expect(screen.getByLabelText("Deine Punkte: 1 von 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /1 Kommentar/ }));
    expect(within(screen.getByRole("complementary", { name: /Kommentare zu B3/ })).getByText("Wegerechte fehlen")).toBeInTheDocument();
  });

  it("recalculates the score live when the own verdict changes and saves it", async () => {
    const posts = setup([entry(ME.id, "B3-01", "fulfilled", 0)]);
    render(<EvaluationView id={4902} me={ME} />);
    await userEvent.click(await screen.findByRole("button", { name: "Checks von B3 aufklappen" }));
    await userEvent.click(within(screen.getByRole("group", { name: "B3-04 bewerten" })).getByRole("button", { name: "✓" }));
    expect(await screen.findByLabelText("Deine Punkte: 2 von 2")).toBeInTheDocument();
    expect(posts).toEqual([{ body: { checks: [{ evaluation_check_id: "B3-04", verdict: "fulfilled", score: null }] }, user: ME.id }]);
    await waitFor(() => expect(screen.getByLabelText("Reifegrad Netzplanung")).toHaveTextContent("33 %"));
  });

  it("is read-only for users who may not evaluate", async () => {
    setup([]);
    render(<EvaluationView id={4902} me={{ ...ME, id: "v", role: "viewer", role_label: "Lesend", can_evaluate: false }} />);
    await screen.findByText("Reifegrad gesamt");
    await userEvent.click(screen.getByRole("button", { name: "Checks von B3 aufklappen" }));
    expect(screen.queryByRole("group", { name: "B3-04 bewerten" })).toBeNull();
    expect(screen.getByText(/Du kannst die Bewertung lesen/)).toBeInTheDocument();
  });
});

describe("K4 history", () => {
  it("lists the change with the group score before and after", async () => {
    setup([entry(RE.id, "B3-04", "not_fulfilled", 0)]);
    render(<HistoryView id={4902} me={ME} />);
    expect(await screen.findByText("Wegerechte fehlen")).toBeInTheDocument();
    expect(screen.getByText("änderte")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Nur Begründungen" }));
    expect(screen.getByText("1 Einträge")).toBeInTheDocument();
  });
});
