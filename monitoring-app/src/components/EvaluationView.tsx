// K1 "Spalte je Prüfer": one column per evaluator, the own column is
// editable, differences are marked, comments per scoring group in the side
// panel. Own verdicts and comments are staged and saved together with
// "Bewertung speichern" at the end of the evaluation. Scores are recalculated
// live from the check verdicts (domain/scoring.ts), other evaluators' changes
// arrive by polling (domain/useEvaluation.ts).
import { Fragment, useEffect, useMemo, useState } from "react";

import type { EvaluationCheck, EvaluationEntry, User, Verdict } from "../api/types";
import { fmtShortDateTime } from "../domain/format";
import { hrefOf, setLeaveGuard } from "../domain/route";
import {
  diverges,
  fmtPercent,
  groupScore,
  overallScore,
  scoringGroups,
  shortOf,
  valuesOf,
  VERDICT_LABEL,
  type GroupScore,
  type ScoringGroup,
} from "../domain/scoring";
import { useEvaluation } from "../domain/useEvaluation";
import { useRequestHeader, RequestTitle } from "./RequestTitle";
import { ErrorNote } from "./small";

export function Avatar({ user, size }: { user: Pick<User, "role" | "role_label">; size?: "s" }) {
  return (
    <span className={`av role-${user.role} ${size === "s" ? "s" : ""}`} title={user.role_label} aria-hidden="true">
      {shortOf(user.role)}
    </span>
  );
}

function checkKind(c: EvaluationCheck): string {
  if (c.check_type === "minimum") return c.alternative_group ? "Mindestanforderung, eine genügt" : "Mindestanforderung";
  const pts = c.graded ? `1–${c.points} Punkte` : `${c.points} ${c.points === 1 ? "Punkt" : "Punkte"}`;
  return c.alternative_group ? `${pts}, oder` : pts;
}

function ScoreValue({ s, max, mark }: { s: GroupScore; max: number; mark?: boolean }) {
  if (max === 0) {
    const ok = s.status === "complete";
    return <span className={`sv ${s.status === "min_failed" ? "bad" : ok ? "ok" : "dim"}`}>{s.status === "empty" ? "–" : ok ? "erfüllt" : s.status === "min_failed" ? "fehlt" : "offen"}</span>;
  }
  return (
    <span className={`sv ${mark ? "diff" : ""}`} title={s.status === "incomplete" ? "Mindestanforderungen noch offen" : s.status === "min_failed" ? "Mindestanforderung nicht erfüllt" : undefined}>
      {s.score ?? "–"}
      {s.status === "incomplete" && <sup>*</sup>}
      {s.status === "min_failed" && <sup>!</sup>}
    </span>
  );
}

function OwnScore({ s, max }: { s: GroupScore; max: number }) {
  if (max === 0) return <ScoreValue s={s} max={max} />;
  return (
    <div className="own-score" aria-label={`Deine Punkte: ${s.score ?? "keine"} von ${max}`}>
      {Array.from({ length: max + 1 }, (_, n) => (
        <i key={n} className={s.score === n ? "on" : ""}>
          {n}
        </i>
      ))}
      {s.status === "incomplete" && <small className="st warn">Mindestanf. offen</small>}
      {s.status === "min_failed" && <small className="st bad">Mindestanf. fehlt</small>}
    </div>
  );
}

function VerdictMark({ e }: { e: EvaluationEntry | undefined }) {
  if (!e || e.verdict === "open") return <span className="vm dim">–</span>;
  return (
    <span className={`vm ${e.verdict === "fulfilled" ? "ok" : "bad"}`} title={VERDICT_LABEL[e.verdict]}>
      {e.verdict === "fulfilled" ? "✓" : "✗"}
      {e.verdict === "fulfilled" && e.score ? ` ${e.score}` : ""}
    </span>
  );
}

function VerdictInput({
  check,
  entry,
  disabled,
  onChange,
}: {
  check: EvaluationCheck;
  entry: EvaluationEntry | undefined;
  disabled: boolean;
  onChange: (verdict: Verdict, score?: number) => void;
}) {
  const v = entry?.verdict ?? "open";
  const options: { verdict: Verdict; score?: number; label: string; title: string }[] = [
    { verdict: "not_fulfilled", label: "✗", title: "nicht erfüllt" },
    ...(check.graded
      ? Array.from({ length: check.points }, (_, i) => ({ verdict: "fulfilled" as Verdict, score: i + 1, label: `✓ ${i + 1}`, title: `erfüllt, ${i + 1} Punkte` }))
      : [{ verdict: "fulfilled" as Verdict, label: "✓", title: "erfüllt" }]),
    { verdict: "open", label: "–", title: "offen (Bewertung zurücknehmen)" },
  ];
  return (
    <div className="seg" role="group" aria-label={`${check.id} bewerten`}>
      {options.map((o) => {
        const on = o.verdict === v && (o.score === undefined || o.score === entry?.score);
        return (
          <button
            key={o.label}
            type="button"
            className={on ? "on" : ""}
            aria-pressed={on}
            title={o.title}
            disabled={disabled}
            onClick={() => !on && onChange(o.verdict, o.score)}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function EvaluationView({ id, me }: { id: number; me: User | null }) {
  const header = useRequestHeader(id);
  const ev = useEvaluation(id, me?.can_evaluate ? me.id : null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [draftCheck, setDraftCheck] = useState<string>("");

  const groups = useMemo(() => scoringGroups(ev.framework ?? []), [ev.framework]);
  const evaluators = ev.state?.evaluators ?? [];
  // own column first, as in the design
  const columns = useMemo(() => {
    const mine = evaluators.filter((u) => u.id === me?.id);
    return [...mine, ...evaluators.filter((u) => u.id !== me?.id)];
  }, [evaluators, me]);
  const canEdit = !!me?.can_evaluate && columns[0]?.id === me.id;

  const values = useMemo(() => new Map(columns.map((u) => [u.id, valuesOf(ev.entries, u.id)])), [columns, ev.entries]);
  const entryOf = (userId: string, checkId: string) => ev.entries.find((e) => e.user_id === userId && e.evaluation_check_id === checkId);
  const scoreOf = (userId: string, g: ScoringGroup) => groupScore(g, values.get(userId) ?? new Map());
  const overall = columns.map((u) => overallScore(ev.framework ?? [], groups, values.get(u.id) ?? new Map()));
  const given = overall.map((o) => o.percent).filter((p): p is number => p !== null);

  const groupOfCheck = useMemo(() => new Map(groups.flatMap((g) => g.checks.map((c) => [c.id, g.key] as const))), [groups]);
  const comments = (key: string) => (ev.history?.items ?? []).filter((h) => h.comment && groupOfCheck.get(h.evaluation_check_id) === key).reverse();
  const userById = new Map(evaluators.map((u) => [u.id, u]));

  const side = groups.find((g) => g.key === selected) ?? groups.find((g) => g.maxScore > 0) ?? null;
  const sideCheck = side && (side.checks.some((c) => c.id === draftCheck) ? draftCheck : (side.checks.find((c) => c.check_type === "points") ?? side.checks[0])?.id);

  const toggle = (key: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });

  const setVerdict = (check: EvaluationCheck, verdict: Verdict, score?: number) => ev.stage(check.id, verdict, score);

  const stageComment = () => {
    if (!me || !sideCheck || !draft.trim()) return;
    ev.stageComment(sideCheck, draft);
    setDraft("");
  };

  const unsaved = ev.draft.size;
  const stagedComments = (key: string) => [...ev.draft].filter(([id, d]) => d.comment && groupOfCheck.get(id) === key);

  // unsaved changes: ask before leaving the page or closing the tab
  useEffect(() => {
    if (!unsaved) return;
    setLeaveGuard(() => window.confirm("Du hast ungespeicherte Änderungen an deiner Bewertung. Verwerfen und die Seite verlassen?"));
    const onUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", onUnload);
    return () => {
      setLeaveGuard(null);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [unsaved]);

  if (ev.error && !ev.state) return <ErrorNote message={ev.error} />;

  return (
    <div className="ev">
      <div className="ev-head">
        <div>
          <div className="crumb">
            <a href="#/">Anträge</a> / {id}
          </div>
          <RequestTitle header={header} />
        </div>
        <div className="who">
          <span className="dim small">Bewerten dürfen:</span>
          {evaluators.map((u) => (
            <span key={u.id} className="chip">
              <Avatar user={u} size="s" /> {u.role_label}
            </span>
          ))}
          <a className="lk" href={hrefOf({ page: "history", id })}>
            Verlauf ansehen
          </a>
        </div>
      </div>
      {ev.error && <ErrorNote message={ev.error} />}

      <div className="ev-grid">
        <section className="ev-table tw" aria-label="Bewertung je Prüfer:in">
          <table>
            <thead>
              <tr>
                <th className="pad">Sub-Kriterium</th>
                {columns.map((u, i) => (
                  <th key={u.id} className={`pad ucol ${i === 0 && canEdit ? "mine" : ""}`}>
                    <span className="uh">
                      <Avatar user={u} />
                      <span>
                        <b>{u.role_label}</b>
                        <small>{u.id === me?.id ? "du" : u.name ?? u.email}</small>
                      </span>
                    </span>
                  </th>
                ))}
                <th className="pad">Kommentare</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const scores = columns.map((u) => scoreOf(u.id, g));
                const diff = g.maxScore > 0 && diverges(scores.map((s) => s.score));
                const ref = scores[0]?.score ?? scores.find((s) => s.score !== null)?.score ?? null;
                const nComments = comments(g.key).length;
                const isOpen = open.has(g.key);
                return (
                  <Fragment key={g.key}>
                    <tr className={`grp-row ${diff ? "diverge" : ""} ${side?.key === g.key ? "focus" : ""}`} onClick={() => toggle(g.key)}>
                      <td className="name">
                        <button type="button" className="exp" aria-expanded={isOpen} aria-label={`Checks von ${g.key} ${isOpen ? "zuklappen" : "aufklappen"}`} onClick={(e) => { e.stopPropagation(); toggle(g.key); }}>
                          {isOpen ? "▾" : "▸"}
                        </button>
                        <span>
                          <span>
                            <b>{g.key}</b> {g.name}
                          </span>
                          <small className="dim">
                            {g.maxScore > 0 ? `max ${g.maxScore}` : "formale Mindestanforderung"} · {g.checks.length} {g.checks.length === 1 ? "Check" : "Checks"}
                          </small>
                          {diff && <span className="badge warn">Einschätzungen weichen ab</span>}
                        </span>
                      </td>
                      {columns.map((u, i) => (
                        <td key={u.id} className={`ucol ${i === 0 && canEdit ? "mine" : ""}`}>
                          {i === 0 && canEdit ? <OwnScore s={scores[i]} max={g.maxScore} /> : <ScoreValue s={scores[i]} max={g.maxScore} mark={diff && scores[i].score !== null && scores[i].score !== ref} />}
                        </td>
                      ))}
                      <td>
                        <button type="button" className={`cbtn ${side?.key === g.key ? "on" : ""} ${nComments ? "" : "none"}`} onClick={(e) => { e.stopPropagation(); setSelected(g.key); }}>
                          💬 {nComments ? `${nComments} ${nComments === 1 ? "Kommentar" : "Kommentare"}` : "Kommentieren"}
                        </button>
                      </td>
                    </tr>
                    {isOpen &&
                      g.checks.map((c) => (
                        <tr key={c.id} className="chk-row">
                          <td className="name">
                            <span>
                              <span className="mono">{c.id}</span> <small className="dim">{checkKind(c)}</small>
                              {(c.description || c.document_category) && <small className="dim block">{c.description ?? c.document_category}</small>}
                            </span>
                          </td>
                          {columns.map((u, i) => (
                            <td key={u.id} className={`ucol ${i === 0 && canEdit ? `mine ${ev.draft.has(c.id) ? "staged" : ""}` : ""}`}>
                              {i === 0 && canEdit ? (
                                <VerdictInput check={c} entry={entryOf(u.id, c.id)} disabled={ev.saving} onChange={(v, s) => setVerdict(c, v, s)} />
                              ) : (
                                <VerdictMark e={entryOf(u.id, c.id)} />
                              )}
                            </td>
                          ))}
                          <td />
                        </tr>
                      ))}
                  </Fragment>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <td className="name">
                  <b>Reifegrad gesamt</b>
                </td>
                {columns.map((u, i) => (
                  <td key={u.id} className={`ucol ${i === 0 && canEdit ? "mine" : ""}`}>
                    <div className="total" aria-label={`Reifegrad ${u.role_label}`}>
                      <b className="mono">{fmtPercent(overall[i].percent)}</b>
                      {overall[i].percent !== null && !overall[i].complete && <small className="dim"> vorläufig</small>}
                      <span className="pbar">
                        <i style={{ width: `${overall[i].percent ?? 0}%` }} />
                      </span>
                    </div>
                  </td>
                ))}
                <td className="dim small">{given.length ? `Spanne ${fmtPercent(Math.min(...given))}–${fmtPercent(Math.max(...given))}` : "noch keine Bewertung"}</td>
              </tr>
            </tfoot>
          </table>
          {canEdit && (
            <div className="submit-bar pad">
              <span className={unsaved ? "warn-text" : "dim"}>
                {unsaved ? `${unsaved} ungespeicherte ${unsaved === 1 ? "Änderung" : "Änderungen"}` : "Keine ungespeicherten Änderungen"}
              </span>
              <button type="button" className="ghost" disabled={!unsaved || ev.saving} onClick={ev.discard}>
                Verwerfen
              </button>
              <button type="button" className="primary" disabled={!unsaved || ev.saving} onClick={() => void ev.submit()}>
                {ev.saving ? "Wird gespeichert …" : "Bewertung speichern"}
              </button>
            </div>
          )}
          <p className="note pad">
            {canEdit
              ? "Deine Spalte ist bearbeitbar und farblich hinterlegt. Die anderen Spalten kannst du lesen, aber nicht ändern. Deine Änderungen und Kommentare werden mit „Bewertung speichern“ gespeichert und sind dann für alle sichtbar. "
              : "Du kannst die Bewertung lesen, aber nicht ändern. "}
            <span className="live">● live</span>{" "}
            {ev.lastSync && <span className="dim">aktualisiert {ev.lastSync.toLocaleTimeString("de-DE")}</span>}
            {" · "}* Mindestanforderungen noch offen, ! Mindestanforderung nicht erfüllt.
          </p>
        </section>

        {side && (
          <aside className="ev-side" aria-label={`Kommentare zu ${side.key}`}>
            <div className="lbl">Kommentare zu</div>
            <h3>
              {side.key} {side.name}
            </h3>
            {side.question && <p className="dim small">{side.question}</p>}
            <div className="tiles">
              {columns.map((u) => (
                <div key={u.id} className="tile">
                  <Avatar user={u} size="s" />
                  <ScoreValue s={scoreOf(u.id, side)} max={side.maxScore} />
                </div>
              ))}
            </div>
            <ul className="thread">
              {stagedComments(side.key).map(([id, d]) => (
                <li key={`draft-${id}`} className="staged">
                  {me && <Avatar user={me} size="s" />}
                  <div>
                    <div className="th">
                      <b>{me?.role_label}</b>
                      <span className="badge warn">nicht gespeichert</span>
                    </div>
                    <div className="dim small">
                      {id} {VERDICT_LABEL[d.verdict]}
                    </div>
                    <p>{d.comment}</p>
                  </div>
                </li>
              ))}
              {comments(side.key).map((h) => {
                const u = userById.get(h.user_id);
                return (
                  <li key={h.id}>
                    {u && <Avatar user={u} size="s" />}
                    <div>
                      <div className="th">
                        <b>{u?.role_label ?? "Unbekannt"}</b>
                        <span className="dim mono small">{fmtShortDateTime(h.timestamp)}</span>
                      </div>
                      <div className="dim small">
                        {h.evaluation_check_id} {VERDICT_LABEL[h.verdict]}
                        {h.pending && " · wird verarbeitet"}
                      </div>
                      <p>{h.comment}</p>
                    </div>
                  </li>
                );
              })}
              {!comments(side.key).length && !stagedComments(side.key).length && <li className="dim small">Noch keine Kommentare.</li>}
            </ul>
            {canEdit && (
              <div className="compose">
                <label className="lbl" htmlFor="ev-comment">
                  Dein Kommentar
                </label>
                <select aria-label="Check des Kommentars" value={sideCheck ?? ""} onChange={(e) => setDraftCheck(e.target.value)}>
                  {side.checks.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.id} ({VERDICT_LABEL[entryOf(me!.id, c.id)?.verdict ?? "open"]})
                    </option>
                  ))}
                </select>
                <textarea id="ev-comment" placeholder="Begründung oder Frage an die anderen" value={draft} onChange={(e) => setDraft(e.target.value)} />
                <button type="button" className="primary" disabled={!draft.trim() || ev.saving} onClick={stageComment}>
                  Kommentar vormerken
                </button>
                <small className="dim">Wird mit „Bewertung speichern“ gespeichert.</small>
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
