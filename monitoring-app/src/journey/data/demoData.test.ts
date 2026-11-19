import { BY_ID, guidance, ME, PASS_THRESHOLD, REQUESTS, SUBS } from ".";

describe("journey demo data", () => {
  it("has the 14 requests of the mockup", () => {
    expect(REQUESTS).toHaveLength(14);
    expect(SUBS.reduce((n, s) => n + s.max, 0)).toBe(11);
  });

  it("derives the focus case Projekt-G02 as in the mockup", () => {
    const r = BY_ID[4902];
    expect(r.subs.B3.state).toBe("zweitpruefung");
    expect(r.subs.B3.turn).toBe("RE");
    expect(r.subs.A1.final).toBe(2);
    expect(r.sum.done).toBe(2);
    expect(r.sum.turns.RE).toEqual(["B3", "D1"]);
    expect(guidance(4902, "B3").suggest).toBe(1);
  });

  it("gives every sub-criterion a history of at least three ratings", () => {
    for (const r of REQUESTS) for (const s of SUBS) {
      const n = r.subs[s.key].events.filter((e) => e.type === "bewertet" || e.type === "geaendert").length;
      expect(n, `${r.id} ${s.key}`).toBeGreaterThanOrEqual(3);
    }
  });

  it("has many sub-criteria waiting for the user", () => {
    const mine = REQUESTS.flatMap((r) => r.sum.turns[ME] ?? []);
    expect(mine.length).toBeGreaterThanOrEqual(10);
    expect(REQUESTS.filter((r) => r.sum.turns[ME]?.length).length).toBeGreaterThanOrEqual(5);
  });

  it("scores Projekt-G02 provisionally above the threshold", () => {
    const r = BY_ID[4902], pts = SUBS.reduce((n, s) => n + (r.subs[s.key].consensus ?? 0), 0);
    expect(pts).toBe(9);
    expect(pts >= PASS_THRESHOLD).toBe(true);
  });
});
