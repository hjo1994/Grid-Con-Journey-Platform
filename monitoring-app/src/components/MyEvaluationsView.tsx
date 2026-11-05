// "Meine Bewertungen": start page after login (picking a user). Lists every
// request the user has evaluated, most recently changed first, with their own
// latest results (Gold + not yet processed inputs). The maturity level is
// computed from the checks as in K1 (domain/scoring.ts); a row opens K1.
import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../api/client";
import type { EvaluationCriterion, User, UserEvaluations } from "../api/types";
import { fmtMW, fmtShortDateTime } from "../domain/format";
import { hrefOf } from "../domain/route";
import { fmtPercent, overallScore, scoringGroups, valuesOf } from "../domain/scoring";
import { ErrorNote } from "./small";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Unerwarteter Fehler beim Laden der Daten.");

export function MyEvaluationsView({ me }: { me: User | null }) {
  const [framework, setFramework] = useState<EvaluationCriterion[] | null>(null);
  const [data, setData] = useState<UserEvaluations | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!me) return;
    const ctrl = new AbortController();
    setData(null);
    Promise.all([api.framework(ctrl.signal), api.myEvaluations(ctrl.signal)])
      .then(([f, d]) => {
        setFramework(f);
        setData(d);
        setError(null);
      })
      .catch((err) => (err as Error)?.name !== "AbortError" && setError(errorText(err)));
    return () => ctrl.abort();
  }, [me]);

  const groups = useMemo(() => scoringGroups(framework ?? []), [framework]);

  if (!me) return <p className="dim">Du bist nicht als Prüfer:in angelegt. Bewertungen kannst du lesen, aber nicht abgeben.</p>;
  if (error) return <ErrorNote message={error} />;

  const items = data?.items ?? [];
  return (
    <div className="ev">
      <div className="toolbar">
        <h2>Meine Bewertungen</h2>
        <span className="dim small">
          {me.role_label} · {me.name ?? me.email} · deine zuletzt gespeicherten Ergebnisse
        </span>
      </div>
      <section className="tw mine-list" aria-label="Meine Bewertungen" aria-busy={!data}>
        <table>
          <thead>
            <tr>
              <th>Antrag</th>
              <th>Projekt</th>
              <th>Technologie</th>
              <th>MW</th>
              <th>Status</th>
              <th>Dein Reifegrad</th>
              <th>Bewertete Checks</th>
              <th>Letzte Änderung</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const overall = overallScore(framework ?? [], groups, valuesOf(item.checks, me.id));
              const rated = item.checks.filter((c) => c.verdict !== "open").length;
              const href = hrefOf({ page: "evaluation", id: item.id_gronos_new });
              return (
                <tr key={item.id_gronos_new} onClick={() => (window.location.hash = href)}>
                  <td className="mono">
                    <a href={href} onClick={(e) => e.stopPropagation()}>
                      {item.id_gronos_new}
                    </a>
                  </td>
                  <td>{item.id_gronos_old ?? "–"}</td>
                  <td>{item.generation_technology ?? "–"}</td>
                  <td className="mono">{fmtMW(item.max_p)}</td>
                  <td>{item.request_status ?? "–"}</td>
                  <td>
                    <div className="total" aria-label={`Reifegrad ${item.id_gronos_new}`}>
                      <b className="mono">{fmtPercent(overall.percent)}</b>
                      {overall.percent !== null && !overall.complete && <small className="dim">vorläufig</small>}
                      <span className="pbar">
                        <i style={{ width: `${overall.percent ?? 0}%` }} />
                      </span>
                    </div>
                  </td>
                  <td className="mono">{rated}</td>
                  <td className="mono">
                    {fmtShortDateTime(item.last_change)}
                    {item.pending && <small className="dim"> · wird verarbeitet</small>}
                  </td>
                </tr>
              );
            })}
            {data && !items.length && (
              <tr>
                <td className="empty" colSpan={8}>
                  {me.can_evaluate ? "Du hast noch keinen Antrag bewertet. In der Übersicht findest du alle Anträge." : "Deine Rolle bewertet nicht. In der Übersicht findest du alle Anträge."}{" "}
                  <a href="#/">Zur Übersicht</a>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
