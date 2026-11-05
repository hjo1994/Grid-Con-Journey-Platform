// Loads framework, current evaluation and history of one request and keeps
// them live: polls every POLL_MS. The user's own changes are staged in a
// draft (verdicts and comments) and only sent with submit() ("Bewertung
// speichern"), as one call with the checks that differ from the user's latest
// saved state. The draft is shown on top of the saved state, so the score is
// recalculated on the click; polling never overwrites it.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { EvaluationCheck, EvaluationCriterion, EvaluationEntry, EvaluationHistory, EvaluationInputItem, EvaluationState, Verdict } from "../api/types";
import { scoreFor, scoringGroups } from "./scoring";

export const POLL_MS = 4000;

/** One staged check: verdict, the chosen points of graded checks, an optional comment. */
export interface DraftItem {
  verdict: Verdict;
  score: number | null;
  comment: string | null;
}

export interface EvaluationData {
  framework: EvaluationCriterion[] | null;
  state: EvaluationState | null;
  history: EvaluationHistory | null;
  /** Current entries incl. the user's staged (unsaved) changes. */
  entries: EvaluationEntry[];
  /** Staged changes by check ID. */
  draft: Map<string, DraftItem>;
  error: string | null;
  saving: boolean;
  lastSync: Date | null;
  stage: (checkId: string, verdict: Verdict, score?: number) => void;
  stageComment: (checkId: string, comment: string) => void;
  discard: () => void;
  submit: () => Promise<boolean>;
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Unerwarteter Fehler beim Laden der Daten.");

/** Does a staged item change the saved entry? Same rule as BronzeToGold. */
function changes(check: EvaluationCheck | undefined, item: DraftItem, saved: EvaluationEntry | undefined): boolean {
  const score = check ? scoreFor(check, item.verdict, item.score ?? undefined) : item.score;
  const valueChanged = item.verdict !== (saved?.verdict ?? "open") || score !== (saved?.score ?? null);
  return valueChanged || (!!item.comment && item.comment !== saved?.comment);
}

export function useEvaluation(idGronosNew: number, userId: string | null): EvaluationData {
  const [framework, setFramework] = useState<EvaluationCriterion[] | null>(null);
  const [state, setState] = useState<EvaluationState | null>(null);
  const [history, setHistory] = useState<EvaluationHistory | null>(null);
  const [draft, setDraft] = useState<Map<string, DraftItem>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([api.evaluation(idGronosNew), api.history(idGronosNew)]);
      if (!alive.current) return;
      setState(s);
      setHistory(h);
      setLastSync(new Date());
      setError(null);
    } catch (err) {
      if (alive.current) setError(errorText(err));
    }
  }, [idGronosNew]);

  useEffect(() => {
    alive.current = true;
    api.framework().then((f) => alive.current && setFramework(f)).catch((err) => alive.current && setError(errorText(err)));
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => {
      alive.current = false;
      clearInterval(t);
    };
  }, [refresh]);

  // a draft belongs to one user
  useEffect(() => setDraft(new Map()), [userId]);

  const checksById = useMemo(() => {
    const m = new Map<string, EvaluationCheck>();
    for (const g of scoringGroups(framework ?? [])) for (const c of g.checks) m.set(c.id, c);
    return m;
  }, [framework]);

  const saved = useCallback(
    (checkId: string) => state?.checks.find((e) => e.user_id === userId && e.evaluation_check_id === checkId),
    [state, userId],
  );

  const put = useCallback(
    (checkId: string, item: DraftItem) =>
      setDraft((d) => {
        const n = new Map(d);
        if (changes(checksById.get(checkId), item, saved(checkId))) n.set(checkId, item);
        else n.delete(checkId);
        return n;
      }),
    [checksById, saved],
  );

  const stage = useCallback(
    (checkId: string, verdict: Verdict, score?: number) => put(checkId, { verdict, score: score ?? null, comment: draft.get(checkId)?.comment ?? null }),
    [put, draft],
  );

  const stageComment = useCallback(
    (checkId: string, comment: string) => {
      const base = draft.get(checkId) ?? { verdict: saved(checkId)?.verdict ?? "open", score: saved(checkId)?.score ?? null, comment: null };
      put(checkId, { ...base, comment: comment.trim() || null });
    },
    [put, draft, saved],
  );

  const discard = useCallback(() => setDraft(new Map()), []);

  const submit = useCallback(async () => {
    if (!userId) return false;
    const items: EvaluationInputItem[] = [...draft]
      .filter(([id, item]) => changes(checksById.get(id), item, saved(id)))
      .map(([id, item]) => ({
        evaluation_check_id: id,
        verdict: item.verdict,
        score: checksById.get(id)?.graded && item.verdict === "fulfilled" ? item.score : null,
        ...(item.comment ? { comment: item.comment } : {}),
      }));
    if (!items.length) {
      setDraft(new Map());
      return true;
    }
    setSaving(true);
    try {
      await api.saveEvaluation(idGronosNew, userId, items);
      await refresh();
      setDraft(new Map());
      return true;
    } catch (err) {
      setError(errorText(err));
      return false;
    } finally {
      setSaving(false);
    }
  }, [idGronosNew, userId, draft, checksById, saved, refresh]);

  const entries = useMemo(() => {
    const base = state?.checks ?? [];
    if (!draft.size || !userId) return base;
    const staged = [...draft].map(([id, item]): EvaluationEntry => {
      const check = checksById.get(id);
      return {
        id: `draft-${id}`,
        user_id: userId,
        evaluation_check_id: id,
        verdict: item.verdict,
        score: check ? scoreFor(check, item.verdict, item.score ?? undefined) : item.score,
        comment: item.comment,
        version: 0,
        timestamp: new Date().toISOString(),
        pending: true,
      };
    });
    return [...base.filter((e) => !(e.user_id === userId && draft.has(e.evaluation_check_id))), ...staged];
  }, [state, draft, userId, checksById]);

  return { framework, state, history, entries, draft, error, saving, lastSync, stage, stageComment, discard, submit };
}
