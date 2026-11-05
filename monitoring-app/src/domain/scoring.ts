// Scoring of the maturity evaluation (Reifegradverfahren), computed live in
// the browser from the check verdicts. Rules derived from the "Ist-Punktzahl
// 50Hz" formulas of the evaluation Excel (see
// input-orchestration/grid_con_ingestion/evaluation_framework.py):
//
// * Sub-criteria with the same scoring_group are scored together (B1+B2, C1+C2).
// * Minimum checks (check_type "minimum") must be fulfilled and give no points.
//   Checks sharing an alternative_group are alternatives: one fulfilled is enough.
//   A failed minimum requirement sets the group to 0.
// * Points checks give their points when fulfilled; the group gets the highest
//   value reached (alternatives), capped at max_score.
// * A group is incomplete while a minimum requirement is still open, or – for
//   groups without minimum checks – while none of its checks is evaluated.
// * Overall (Reifegrad) = Σ criterion weight × (points of the criterion /
//   max points of the criterion), in percent.

import type { EvaluationCheck, EvaluationCriterion, EvaluationEntry, Verdict } from "../api/types";

export interface ScoringGroup {
  key: string;
  name: string;
  criterionId: string;
  maxScore: number;
  question: string | null;
  checks: EvaluationCheck[];
  subCriterionIds: string[];
}

export type GroupStatus = "complete" | "incomplete" | "min_failed" | "empty";

export interface GroupScore {
  score: number | null; // null = nothing evaluated in this group
  status: GroupStatus;
}

export interface OverallScore {
  percent: number | null;
  complete: boolean;
}

/** Verdict and score per check id of one user. */
export type CheckValues = Map<string, Pick<EvaluationEntry, "verdict" | "score">>;

export function scoringGroups(framework: EvaluationCriterion[]): ScoringGroup[] {
  const groups = new Map<string, ScoringGroup>();
  for (const c of framework) {
    for (const s of c.sub_criteria) {
      const g = groups.get(s.scoring_group) ?? {
        key: s.scoring_group,
        name: s.scoring_group_name,
        criterionId: c.id,
        maxScore: s.max_score,
        question: s.question,
        checks: [],
        subCriterionIds: [],
      };
      g.checks.push(...s.checks);
      g.subCriterionIds.push(s.id);
      groups.set(s.scoring_group, g);
    }
  }
  return [...groups.values()];
}

const evaluated = (v: Verdict | undefined) => v === "fulfilled" || v === "not_fulfilled";

export function groupScore(group: ScoringGroup, values: CheckValues): GroupScore {
  const verdict = (c: EvaluationCheck) => values.get(c.id)?.verdict;
  if (!group.checks.some((c) => evaluated(verdict(c)))) return { score: null, status: "empty" };

  // minimum requirements, alternatives grouped
  const units = new Map<string, EvaluationCheck[]>();
  for (const c of group.checks.filter((c) => c.check_type === "minimum")) {
    const key = c.alternative_group ?? c.id;
    units.set(key, [...(units.get(key) ?? []), c]);
  }
  let incomplete = false;
  for (const checks of units.values()) {
    if (checks.some((c) => verdict(c) === "fulfilled")) continue;
    if (checks.every((c) => verdict(c) === "not_fulfilled")) return { score: 0, status: "min_failed" };
    incomplete = true;
  }

  let points = 0;
  for (const c of group.checks.filter((c) => c.check_type === "points")) {
    const v = values.get(c.id);
    if (v?.verdict === "fulfilled") points = Math.max(points, c.graded ? v.score ?? 0 : c.points);
  }
  return { score: Math.min(points, group.maxScore), status: incomplete ? "incomplete" : "complete" };
}

export function overallScore(framework: EvaluationCriterion[], groups: ScoringGroup[], values: CheckValues): OverallScore {
  let percent = 0;
  let any = false;
  let complete = true;
  for (const c of framework) {
    const own = groups.filter((g) => g.criterionId === c.id);
    const scores = own.map((g) => groupScore(g, values));
    if (scores.some((s) => s.status !== "complete")) complete = false;
    const max = own.reduce((sum, g) => sum + g.maxScore, 0);
    if (c.weight === 0 || max === 0) continue;
    const got = scores.reduce((sum, s) => sum + (s.score ?? 0), 0);
    if (scores.some((s) => s.score !== null)) any = true;
    percent += c.weight * (got / max);
  }
  return { percent: any ? Math.round(percent * 1000) / 10 : null, complete };
}

/** Values of one user from the current evaluation entries. */
export function valuesOf(entries: EvaluationEntry[], userId: string): CheckValues {
  return new Map(entries.filter((e) => e.user_id === userId).map((e) => [e.evaluation_check_id, { verdict: e.verdict, score: e.score }]));
}

/** Score that a verdict gives a check, as the backend stores it. */
export function scoreFor(check: EvaluationCheck, verdict: Verdict, graded?: number): number | null {
  if (verdict === "open") return null;
  if (verdict === "not_fulfilled" || check.check_type === "minimum") return 0;
  return check.graded ? graded ?? check.points : check.points;
}

/** Do the evaluators disagree on a group? Only users who scored it count. */
export function diverges(scores: (number | null)[]): boolean {
  const given = scores.filter((s): s is number => s !== null);
  return new Set(given).size > 1;
}

export function fmtPercent(p: number | null): string {
  return p === null ? "–" : `${Math.round(p)} %`;
}

export const ROLE_SHORT: Record<string, string> = { netzplanung: "NP", flaechen_recht: "RE", finanzen: "FI" };
export const shortOf = (role: string) => ROLE_SHORT[role] ?? role.slice(0, 2).toUpperCase();

/** Group score of the entry's user before and after each history entry
 * (history as the API returns it, newest first). */
export function replay(
  history: { id: string; user_id: string; evaluation_check_id: string; verdict: Verdict; score: number | null; scoring_group: string; timestamp: string }[],
  groups: ScoringGroup[],
): Map<string, { before: number | null; after: number | null }> {
  const byKey = new Map(groups.map((g) => [g.key, g]));
  const values = new Map<string, CheckValues>();
  const result = new Map<string, { before: number | null; after: number | null }>();
  for (const e of [...history].reverse()) {
    const own = values.get(e.user_id) ?? new Map();
    values.set(e.user_id, own);
    const group = byKey.get(e.scoring_group);
    const before = group ? groupScore(group, own).score : null;
    own.set(e.evaluation_check_id, { verdict: e.verdict, score: e.score });
    const after = group ? groupScore(group, own).score : null;
    result.set(e.id, { before, after });
  }
  return result;
}

export const VERDICT_LABEL: Record<Verdict, string> = { fulfilled: "erfüllt", not_fulfilled: "nicht erfüllt", open: "offen" };
