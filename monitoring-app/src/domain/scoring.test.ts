import type { EvaluationEntry, Verdict } from "../api/types";
import { FRAMEWORK } from "../test/fixtures";
import { diverges, groupScore, overallScore, replay, scoreFor, scoringGroups, type CheckValues } from "./scoring";

const groups = scoringGroups(FRAMEWORK);
const g = (key: string) => groups.find((x) => x.key === key)!;
const vals = (o: Record<string, [Verdict, number | null]>): CheckValues => new Map(Object.entries(o).map(([k, [verdict, score]]) => [k, { verdict, score }]));

describe("scoring", () => {
  it("joins sub-criteria of one scoring group", () => {
    expect(groups.map((x) => x.key)).toEqual(["F1", "B1+B2", "B3", "C1"]);
    expect(g("B1+B2").checks.map((c) => c.id)).toEqual(["B1-01", "B2-06"]);
  });

  it("takes the highest fulfilled points check once the minimum is met", () => {
    expect(groupScore(g("B3"), vals({}))).toEqual({ score: null, status: "empty" });
    expect(groupScore(g("B3"), vals({ "B3-03": ["fulfilled", 1] }))).toEqual({ score: 1, status: "incomplete" });
    expect(groupScore(g("B3"), vals({ "B3-01": ["fulfilled", 0], "B3-03": ["fulfilled", 1], "B3-04": ["fulfilled", 2] }))).toEqual({ score: 2, status: "complete" });
    expect(groupScore(g("B3"), vals({ "B3-01": ["not_fulfilled", 0], "B3-04": ["fulfilled", 2] }))).toEqual({ score: 0, status: "min_failed" });
  });

  it("treats alternative minimum checks as 'one is enough' and uses graded scores", () => {
    expect(groupScore(g("C1"), vals({ "C1-01": ["not_fulfilled", 0], "C1-02": ["fulfilled", 0], "D1-01": ["fulfilled", 1] }))).toEqual({ score: 1, status: "complete" });
    expect(groupScore(g("C1"), vals({ "C1-01": ["not_fulfilled", 0], "C1-02": ["not_fulfilled", 0] })).status).toBe("min_failed");
  });

  it("weights criteria by their share of the maximum", () => {
    const v = vals({ "B1-01": ["fulfilled", 0], "B2-06": ["fulfilled", 1], "B3-01": ["fulfilled", 0], "B3-03": ["fulfilled", 1], "F.1.1": ["fulfilled", 0] });
    // B: (1 + 1) / 3 * 0.5 = 33.3 %, C: nothing
    expect(overallScore(FRAMEWORK, groups, v)).toEqual({ percent: 33.3, complete: false });
    expect(overallScore(FRAMEWORK, groups, vals({})).percent).toBeNull();
  });

  it("derives stored scores and divergence", () => {
    expect(scoreFor(g("B3").checks[2], "fulfilled")).toBe(2);
    expect(scoreFor(g("B3").checks[0], "fulfilled")).toBe(0);
    expect(scoreFor(g("B3").checks[2], "open")).toBeNull();
    expect(diverges([1, null, 1])).toBe(false);
    expect(diverges([1, 0, 1])).toBe(true);
  });

  it("replays the history to get the group score before and after an entry", () => {
    const e = (id: string, check: string, verdict: Verdict, score: number): EvaluationEntry & { scoring_group: string } => ({
      id, user_id: "u", evaluation_check_id: check, verdict, score, comment: null, version: 1, timestamp: id, pending: false, scoring_group: "B3",
    });
    const history = [e("3", "B3-04", "not_fulfilled", 0), e("2", "B3-04", "fulfilled", 2), e("1", "B3-01", "fulfilled", 0)];
    const r = replay(history, groups);
    expect(r.get("1")).toEqual({ before: null, after: 0 });
    expect(r.get("2")).toEqual({ before: 0, after: 2 });
    expect(r.get("3")).toEqual({ before: 2, after: 0 });
  });
});
