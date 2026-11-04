// Loads framework, current evaluation and history of one request and keeps
// them live: polls every POLL_MS and applies the user's own changes
// optimistically, so the score is recalculated on the click, not after the
// round trip.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { EvaluationCriterion, EvaluationEntry, EvaluationHistory, EvaluationInputItem, EvaluationState } from "../api/types";
import { scoreFor, scoringGroups } from "./scoring";

export const POLL_MS = 4000;

export interface EvaluationData {
  framework: EvaluationCriterion[] | null;
  state: EvaluationState | null;
  history: EvaluationHistory | null;
  /** Current entries incl. the user's unsaved (optimistic) changes. */
  entries: EvaluationEntry[];
  error: string | null;
  saving: boolean;
  lastSync: Date | null;
  save: (items: EvaluationInputItem[]) => Promise<boolean>;
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Unerwarteter Fehler beim Laden der Daten.");

export function useEvaluation(idGronosNew: number, userId: string | null): EvaluationData {
  const [framework, setFramework] = useState<EvaluationCriterion[] | null>(null);
  const [state, setState] = useState<EvaluationState | null>(null);
  const [history, setHistory] = useState<EvaluationHistory | null>(null);
  const [optimistic, setOptimistic] = useState<EvaluationEntry[]>([]);
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

  const checksById = useMemo(() => {
    const m = new Map<string, EvaluationCriterion["sub_criteria"][number]["checks"][number]>();
    for (const g of scoringGroups(framework ?? [])) for (const c of g.checks) m.set(c.id, c);
    return m;
  }, [framework]);

  const save = useCallback(
    async (items: EvaluationInputItem[]) => {
      if (!userId) return false;
      const now = new Date().toISOString();
      setOptimistic(
        items.map((i) => {
          const check = checksById.get(i.evaluation_check_id);
          return {
            id: `local-${i.evaluation_check_id}`,
            user_id: userId,
            evaluation_check_id: i.evaluation_check_id,
            verdict: i.verdict,
            score: check ? scoreFor(check, i.verdict, i.score ?? undefined) : i.score ?? null,
            comment: i.comment ?? null,
            version: 0,
            timestamp: now,
            pending: true,
          };
        }),
      );
      setSaving(true);
      try {
        await api.saveEvaluation(idGronosNew, userId, items);
        await refresh();
        return true;
      } catch (err) {
        setError(errorText(err));
        return false;
      } finally {
        setOptimistic([]);
        setSaving(false);
      }
    },
    [idGronosNew, userId, checksById, refresh],
  );

  const entries = useMemo(() => {
    const base = state?.checks ?? [];
    if (!optimistic.length) return base;
    const key = (e: EvaluationEntry) => `${e.user_id}|${e.evaluation_check_id}`;
    const over = new Map(optimistic.map((e) => [key(e), e]));
    return [...base.filter((e) => !over.has(key(e))), ...optimistic];
  }, [state, optimistic]);

  return { framework, state, history, entries, error, saving, lastSync, save };
}
