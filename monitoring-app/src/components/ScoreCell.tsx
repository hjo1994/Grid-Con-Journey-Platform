// Reifegrad in the overview (design E): one number per request plus one dot
// per evaluator. Hovering or focusing the cell shows the evaluators' values.
// The numbers come from the backend (GET /evaluation-scores).
import { useState, type SyntheticEvent } from "react";

import type { EvaluationScoreSummary, ReviewerSummary } from "../api/types";
import { fmtShortDateTime } from "../domain/format";
import { hrefOf } from "../domain/route";
import { fmtPercent } from "../domain/scoring";

/** filled = complete, partial = started, open = nothing yet, dev = differs from the others */
export function dotState(r: ReviewerSummary): "dev" | "done" | "partial" | "open" {
  if (r.deviates) return "dev";
  if (r.complete) return "done";
  return r.percent !== null ? "partial" : "open";
}

const DOT_LABEL = { dev: "weicht ab", done: "fertig", partial: "begonnen", open: "offen" } as const;

function Popover({ s, at }: { s: EvaluationScoreSummary; at: DOMRect }) {
  // fixed, so the table's scroll container does not clip it
  const style = { top: at.bottom + 6, left: Math.max(8, Math.min(at.left, window.innerWidth - 280)) };
  return (
    <div className="score-pop" role="tooltip" style={style}>
      <b>
        Reifegrad {fmtPercent(s.percent)}
        {!s.complete && <span className="dim"> · vorläufig</span>}
      </b>
      <table>
        <tbody>
          {s.reviewers.map((r) => (
            <tr key={r.user_id}>
              <td>
                <span className={`dot ${dotState(r)}`} aria-hidden="true" /> {r.short} · {r.role_label}
              </td>
              <td className="r mono">{r.percent === null ? <span className="dim">offen</span> : fmtPercent(r.percent)}</td>
              <td className="dim">{r.last_change ? fmtShortDateTime(r.last_change) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {(s.diverging_groups.length > 0 || s.comment_count > 0) && (
        <span className="warn-text small">
          {[
            s.diverging_groups.length ? `${s.diverging_groups.length} ${s.diverging_groups.length === 1 ? "Gruppe" : "Gruppen"} abweichend (${s.diverging_groups.join(", ")})` : null,
            s.comment_count ? `${s.comment_count} ${s.comment_count === 1 ? "Kommentar" : "Kommentare"}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      )}
    </div>
  );
}

export function ScoreCell({ ticket, summary, loaded }: { ticket: number | null; summary: EvaluationScoreSummary | undefined; loaded: boolean }) {
  const [at, setAt] = useState<DOMRect | null>(null);
  if (ticket === null) return <span className="dim">–</span>;
  if (!summary) return <span className="dim" aria-label={loaded ? "Reifegrad nicht verfügbar" : "Reifegrad wird geladen"}>{loaded ? "–" : "…"}</span>;
  if (summary.percent === null) return <span className="openb">nicht bewertet</span>;
  const label = `Reifegrad ${fmtPercent(summary.percent)}, ${summary.reviewers.map((r) => `${r.short} ${DOT_LABEL[dotState(r)]}`).join(", ")}`;
  const show = (e: SyntheticEvent<HTMLElement>) => setAt(e.currentTarget.getBoundingClientRect());
  return (
    <span className="sc" onMouseEnter={show} onMouseLeave={() => setAt(null)}>
      <a
        href={hrefOf({ page: "evaluation", id: ticket })}
        className={`score ${summary.complete ? "" : "prov"}`}
        aria-label={label}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
        onFocus={show}
        onBlur={() => setAt(null)}
      >
        {fmtPercent(summary.percent)}
      </a>
      <span className="dots" aria-hidden="true">
        {summary.reviewers.map((r) => (
          <i key={r.user_id} className={`dot ${dotState(r)}`} />
        ))}
      </span>
      {at && <Popover s={summary} at={at} />}
    </span>
  );
}
