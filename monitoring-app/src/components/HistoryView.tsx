// K4 "Verlauf": current score per user and scoring group on the left, the
// change log of all users on the right (who rated what, when and why).
import { useMemo, useState } from "react";

import type { HistoryEntry, User } from "../api/types";
import { hrefOf } from "../domain/route";
import { diverges, groupScore, replay, scoringGroups, valuesOf, VERDICT_LABEL } from "../domain/scoring";
import { useEvaluation } from "../domain/useEvaluation";
import { Avatar } from "./EvaluationView";
import { RequestTitle, useRequestHeader } from "./RequestTitle";
import { ErrorNote } from "./small";

type Filter = "all" | "ratings" | "comments";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Alles" },
  { key: "ratings", label: "Nur Bewertungen" },
  { key: "comments", label: "Nur Begründungen" },
];

// One input can set several checks of a group at once; the log shows it as
// one line per user, input and scoring group (as in the design).
interface LogLine extends HistoryEntry {
  checks: HistoryEntry[];
  first: HistoryEntry;
}

function collapse(items: HistoryEntry[]): LogLine[] {
  const lines: LogLine[] = [];
  for (const h of items) {
    const last = lines.at(-1);
    if (last && last.user_id === h.user_id && last.timestamp === h.timestamp && last.scoring_group === h.scoring_group && !h.comment && !last.comment) {
      last.checks.push(h);
      last.first = h;
      if (h.action === "changed") last.action = "changed";
      continue;
    }
    lines.push({ ...h, checks: [h], first: h });
  }
  return lines;
}

const VERB = { rated: "bewertete", changed: "änderte", commented: "kommentierte" } as const;

function dayOf(iso: string) {
  return new Date(iso).toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" });
}

export function HistoryView({ id, me }: { id: number; me: User | null }) {
  const header = useRequestHeader(id);
  const ev = useEvaluation(id, me?.can_evaluate ? me.id : null);
  const [filter, setFilter] = useState<Filter>("all");
  const [group, setGroup] = useState<string | null>(null);

  const groups = useMemo(() => scoringGroups(ev.framework ?? []).filter((g) => g.maxScore > 0), [ev.framework]);
  const allGroups = useMemo(() => scoringGroups(ev.framework ?? []), [ev.framework]);
  const evaluators = ev.state?.evaluators ?? [];
  const items = ev.history?.items ?? [];
  const effects = useMemo(() => replay(items, allGroups), [items, allGroups]);
  const userById = new Map(evaluators.map((u) => [u.id, u]));

  const shown = collapse(
    items.filter(
      (h) =>
        (filter === "all" || (filter === "ratings" ? h.action !== "commented" : !!h.comment)) && (group === null || h.scoring_group === group),
    ),
  );
  const byDay: [string, LogLine[]][] = [];
  for (const h of shown) {
    const d = dayOf(h.timestamp);
    if (byDay.at(-1)?.[0] === d) byDay.at(-1)![1].push(h);
    else byDay.push([d, [h]]);
  }

  if (ev.error && !ev.state) return <ErrorNote message={ev.error} />;

  return (
    <div className="ev">
      <div className="ev-head">
        <div>
          <div className="crumb">
            <a href="#/">Anträge</a> / <a href={hrefOf({ page: "evaluation", id })}>{id}</a> / Verlauf
          </div>
          <RequestTitle header={header} subtitle="Wer hat was wann bewertet und warum" />
        </div>
        <div className="who" role="group" aria-label="Zeigen">
          <span className="dim small">Zeigen:</span>
          {FILTERS.map((f) => (
            <button key={f.key} type="button" className={`fbtn ${filter === f.key ? "on" : ""}`} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
      </div>
      {ev.error && <ErrorNote message={ev.error} />}

      <div className="hist-grid">
        <section className="box">
          <h4>
            Aktueller Stand <small>Zeile wählen, um den Verlauf darauf einzugrenzen.</small>
          </h4>
          <table className="cur">
            <thead>
              <tr>
                <th>Sub-Kriterium</th>
                {evaluators.map((u) => (
                  <th key={u.id} className="c">
                    <Avatar user={u} size="s" />
                  </th>
                ))}
                <th className="r">Änder.</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const scores = evaluators.map((u) => groupScore(g, valuesOf(ev.entries, u.id)).score);
                const diff = diverges(scores);
                const ref = scores.find((s) => s !== null) ?? null;
                const changes = items.filter((h) => h.scoring_group === g.key && h.action === "changed").length;
                return (
                  <tr key={g.key} className={group === g.key ? "sel" : undefined} tabIndex={0} aria-selected={group === g.key}
                    onClick={() => setGroup((x) => (x === g.key ? null : g.key))}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setGroup((x) => (x === g.key ? null : g.key)); } }}>
                    <td>
                      <b>{g.key}</b> {g.name}
                    </td>
                    {scores.map((s, i) => (
                      <td key={evaluators[i].id} className="c">
                        <span className={`sv ${diff && s !== null && s !== ref ? "diff" : ""}`}>{s ?? "–"}</span>
                      </td>
                    ))}
                    <td className="r dim">{changes ? `${changes}×` : "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="note">Abweichende Werte sind markiert.{group && <> Gefiltert auf {group}, <button type="button" className="linkbtn" onClick={() => setGroup(null)}>alle zeigen</button>.</>}</p>
        </section>

        <section className="box">
          <h4>
            Verlauf <small>{shown.length} Einträge</small>
          </h4>
          {!shown.length && <p className="dim">Noch keine Einträge.</p>}
          {byDay.map(([day, entries]) => (
            <div key={day} className="day">
              <div className="lbl">{day}</div>
              <ol className="log">
                {entries.map((h) => {
                  const u = userById.get(h.user_id);
                  const before = effects.get(h.first.id)?.before ?? null;
                  const after = effects.get(h.id)?.after ?? null;
                  return (
                    <li key={h.id} className={h.action === "commented" ? "cmt" : ""}>
                      {u && <Avatar user={u} size="s" />}
                      <div className="lb">
                        <div className="line">
                          <b>{u?.role_label ?? "Unbekannt"}</b> {VERB[h.action]} <b className="mono">{h.scoring_group}</b>
                          {h.action !== "commented" && (
                            <span className="delta">
                              {before === null ? <span className="dim">neu</span> : <s>{before}</s>} → <span className="sv">{after ?? "–"}</span>
                            </span>
                          )}
                          <span className="dim small">
                            {h.checks.length > 3
                              ? `${h.checks.length} Checks`
                              : [...h.checks].reverse().map((c) => `${c.evaluation_check_id} ${VERDICT_LABEL[c.verdict]}`).join(", ")}
                            {h.checks.some((c) => c.pending) && " · wird verarbeitet"}
                          </span>
                          <span className="time mono dim">{new Date(h.timestamp).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}</span>
                        </div>
                        {h.comment && <p className={`quote role-${u?.role ?? ""}`}>{h.comment}</p>}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
