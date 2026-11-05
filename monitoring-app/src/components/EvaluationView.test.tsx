import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { EvaluationEntry, RequestEvaluationScores, User } from "../api/types";
import { FRAMEWORK } from "../test/fixtures";
import { EvaluationView } from "./EvaluationView";
import { HistoryView } from "./HistoryView";
import { MyEvaluationsView } from "./MyEvaluationsView";

const ME: User = { id: "u-np", email: "np@x", name: "J. H.", role: "netzplanung", role_label: "Netzplanung", can_evaluate: true };
const RE: User = { id: "u-re", email: "re@x", name: "A. Becker", role: "flaechen_recht", role_label: "Flächen & Recht", can_evaluate: true };
const entry = (user: string, check: string, verdict: EvaluationEntry["verdict"], score: number | null, comment: string | null = null): EvaluationEntry => ({
  id: `${user}-${check}-${verdict}`, user_id: user, evaluation_check_id: check, verdict, score, comment, version: 1, timestamp: "2026-11-03T09:12:00Z", pending: false,
});

// GET …/evaluation-scores as the backend returns it: per evaluator the latest
// check results grouped by sub-criterion (the computed sums are not used by
// the view, which recomputes them from the checks).
function scoresOf(evaluators: User[], entries: EvaluationEntry[]): RequestEvaluationScores {
  return {
    id_gronos_new: 4902,
    last_change: null,
    combined: { percent: null, method: "mean", done: 0, total: evaluators.length, complete: false, diverging_groups: [] },
    reviewers: evaluators.map((user) => ({
      user, percent: null, complete: false, deviates: false, last_change: null, groups: [],
      sub_criteria: FRAMEWORK.flatMap((c) => c.sub_criteria.map((sc) => ({
        sub_criterion_id: sc.id, scoring_group: sc.scoring_group, criterion_id: c.id, points: null,
        checks: sc.checks.flatMap((k) => entries.filter((e) => e.user_id === user.id && e.evaluation_check_id === k.id).map((e) => ({
          ...e, sub_criterion_id: sc.id, check_type: k.check_type, points: k.points, graded: k.graded, alternative_group: k.alternative_group,
        }))),
      }))),
    })),
  };
}

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
    if (url.pathname.endsWith("/evaluation-scores")) return json(scoresOf([ME, RE], current));
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

  it("stages own verdicts and saves them only with „Bewertung speichern“", async () => {
    const posts = setup([entry(ME.id, "B3-01", "fulfilled", 0)]);
    render(<EvaluationView id={4902} me={ME} />);
    await userEvent.click(await screen.findByRole("button", { name: "Checks von B3 aufklappen" }));
    const save = screen.getByRole("button", { name: "Bewertung speichern" });
    expect(save).toBeDisabled();
    await userEvent.click(within(screen.getByRole("group", { name: "B3-04 bewerten" })).getByRole("button", { name: "✓" }));
    expect(screen.getByLabelText("Deine Punkte: 2 von 2")).toBeInTheDocument();       // recalculated on the click
    expect(screen.getByText("1 ungespeicherte Änderung")).toBeInTheDocument();
    expect(posts).toEqual([]);                                                          // nothing saved yet

    await userEvent.click(save);
    await waitFor(() => expect(posts).toEqual([{ body: { checks: [{ evaluation_check_id: "B3-04", verdict: "fulfilled", score: null }] }, user: ME.id }]));
    expect(await screen.findByText("Keine ungespeicherten Änderungen")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Reifegrad Netzplanung")).toHaveTextContent("33 %"));
  });

  it("sends only checks that differ from the saved state, with staged comments in the same call", async () => {
    const posts = setup([entry(ME.id, "B3-01", "fulfilled", 0)]);
    render(<EvaluationView id={4902} me={ME} />);
    await userEvent.click(await screen.findByRole("button", { name: "Checks von B3 aufklappen" }));
    const b301 = within(screen.getByRole("group", { name: "B3-01 bewerten" }));
    await userEvent.click(b301.getByRole("button", { name: "✗" }));
    await userEvent.click(b301.getByRole("button", { name: "✓" }));                      // back to the saved value
    expect(screen.getByText("Keine ungespeicherten Änderungen")).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("group", { name: "B3-04 bewerten" })).getByRole("button", { name: "✗" }));

    await userEvent.click(screen.getByRole("button", { name: /1 Kommentar/ }));
    await userEvent.selectOptions(screen.getByLabelText("Check des Kommentars"), "B3-01");
    await userEvent.type(screen.getByPlaceholderText("Begründung oder Frage an die anderen"), "Trasse geprüft");
    await userEvent.click(screen.getByRole("button", { name: "Kommentar vormerken" }));
    expect(screen.getByText("nicht gespeichert")).toBeInTheDocument();
    expect(screen.getByText("2 ungespeicherte Änderungen")).toBeInTheDocument();
    expect(posts).toEqual([]);

    await userEvent.click(screen.getByRole("button", { name: "Bewertung speichern" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({ user: ME.id, body: { checks: [
      { evaluation_check_id: "B3-04", verdict: "not_fulfilled", score: null },
      { evaluation_check_id: "B3-01", verdict: "fulfilled", score: null, comment: "Trasse geprüft" },
    ] } });
  });

  it("loads the scores once and again only after saving or „Neu laden“", async () => {
    setup([entry(ME.id, "B3-01", "fulfilled", 0)]);
    const fetch = vi.mocked(globalThis.fetch);
    render(<EvaluationView id={4902} me={ME} />);
    await screen.findByText("Reifegrad gesamt");
    const loads = () => fetch.mock.calls.filter(([u]) => String(u).includes("/evaluation-scores")).length;
    await new Promise((r) => setTimeout(r, 50));
    expect(loads()).toBe(1);
    await userEvent.click(screen.getByRole("button", { name: "Neu laden" }));
    await waitFor(() => expect(loads()).toBe(2));
  });

  it("discards staged changes", async () => {
    const posts = setup([]);
    render(<EvaluationView id={4902} me={ME} />);
    await userEvent.click(await screen.findByRole("button", { name: "Checks von B3 aufklappen" }));
    await userEvent.click(within(screen.getByRole("group", { name: "B3-04 bewerten" })).getByRole("button", { name: "✓" }));
    expect(screen.getByLabelText("Deine Punkte: 2 von 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Verwerfen" }));
    expect(screen.getByText("Keine ungespeicherten Änderungen")).toBeInTheDocument();
    expect(screen.queryByLabelText("Deine Punkte: 2 von 2")).toBeNull();
    expect(posts).toEqual([]);
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

describe("Meine Bewertungen", () => {
  it("lists the own latest results, newest first, linking to K1", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.pathname.endsWith("/evaluation-framework")) return json(FRAMEWORK);
      if (url.pathname.endsWith(`/users/${ME.id}/evaluations`))
        return json({ user: ME, total: 2, items: [
          { id_gronos_new: 5100, id_gronos_old: "Projekt-H01", generation_technology: "Wind", max_p: 120, request_status: "Eingestellt", last_change: "2026-11-04T15:00:00Z", pending: true,
            checks: [entry(ME.id, "B3-01", "fulfilled", 0), entry(ME.id, "B3-04", "fulfilled", 2)] },
          { id_gronos_new: 4902, id_gronos_old: "Projekt-G02", generation_technology: "Photovoltaik", max_p: 300, request_status: null, last_change: "2026-11-03T09:12:00Z", pending: false,
            checks: [entry(ME.id, "B3-04", "not_fulfilled", 0)] },
        ] });
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    render(<MyEvaluationsView me={ME} />);
    const link = await screen.findByRole("link", { name: "5100" });
    expect(link).toHaveAttribute("href", "#/antraege/5100/bewertung");
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["5100", "4902"]);
    expect(screen.getByLabelText("Reifegrad 5100")).toHaveTextContent("33 %");
    expect(within(rows[0]).getByText(/wird verarbeitet/)).toBeInTheDocument();
  });

  it("explains an empty list", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).includes("/evaluation-framework") ? FRAMEWORK : { user: ME, total: 0, items: [] };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    render(<MyEvaluationsView me={ME} />);
    expect(await screen.findByText(/Du hast noch keinen Antrag bewertet/)).toBeInTheDocument();
  });
});
