// Requests overview, variant A "Register" (mockup cockpit.js, OV.a): the
// table as known plus a "Bewertung" column with a thin bar (one segment per
// sub-criterion) and one sentence where the evaluation stands.
import { useEffect, useMemo, useState, type MouseEvent } from "react";

import { days, fmt, ME, PASS_THRESHOLD, REQUESTS, ROLES, SUB, SUBS, TODAY, type Req, type Role, type Sub, type SubState } from "./data";
import { isSeen, markSeen } from "./ui";

interface Info {
  r: Req;
  subs: { s: Sub; st: SubState }[];
  turns: Partial<Record<Role, string[]>>;
  mine: number;
  fin: boolean;
  ok: boolean;
  wait: number;
}

const INFO: Info[] = REQUESTS.map((r) => {
  const subs = SUBS.map((s) => ({ s, st: r.subs[s.key] })), open = subs.filter((x) => x.st.state !== "fertig");
  const pts = subs.reduce((n, x) => n + (x.st.consensus ?? 0), 0), turns = r.sum.turns;
  const w = open.filter((x) => x.st.turn && x.st.since).sort((a, b) => +a.st.since! - +b.st.since!)[0];
  return { r, subs, turns, mine: (turns[ME] || []).length, fin: !open.length, ok: pts >= PASS_THRESHOLD, wait: w ? days(w.st.since) : 0 };
});
// open first, then those waiting for me, then longest waiting
const ORD = INFO.slice().sort((a, b) => (+a.fin - +b.fin) || (+(b.mine > 0) - +(a.mine > 0)) || (b.wait - a.wait));

// Processing status of the request, 1 to 5 (demo value as in the mockup)
const gronosStatus = (r: Req) => (r.id % 5) + 1;

function evalState(i: Info) {
  const nf = i.subs.filter((x) => x.st.state === "fertig").length, my = i.turns[ME] || [];
  const md = my.length ? Math.max(...my.map((k) => (i.r.subs[k].since ? days(i.r.subs[k].since) : 0))) : 0;
  const others = (Object.keys(i.turns) as Role[]).filter((k) => k !== ME);
  if (i.fin) return { k: "fin", t: "Abgeschlossen", s: <span className={`pf ${i.ok ? "ok" : "no"}`}>{i.ok ? "bestanden" : "nicht bestanden"}</span>, w: i.ok ? "bestanden" : "nicht bestanden" };
  if (i.mine) return { k: "me", t: `Du bist bei ${my.map((k) => SUB[k].label).join(", ")} dran`, s: `seit ${md} ${md === 1 ? "Tag" : "Tagen"} · ${nf} von 7 festgelegt`, w: "" };
  return {
    k: "ot",
    t: `Bei ${ROLES[others[0]].name}${others.length > 1 ? ` und ${others.length - 1} ${others.length > 2 ? "weiteren" : "weiterer Rolle"}` : ""}`,
    s: `${nf} von 7 festgelegt · wartet ${i.wait} ${i.wait === 1 ? "Tag" : "Tage"}`,
    w: "",
  };
}
const segCls = (x: { st: SubState }) => (x.st.state === "fertig" ? "f" : x.st.turn === ME ? "m" : x.st.state === "offen" ? "" : "l");

type Key = "id" | "name" | "kunde" | "tech" | "mw" | "uw" | "start" | "gs" | "ev";
const HEAD: [Key, string, string?][] = [["id", "Ticket", "r"], ["name", "Projekt"], ["kunde", "Kunde"], ["tech", "Technologie"], ["mw", "MW", "r"], ["uw", "Umspannwerk"], ["start", "Eingang"], ["gs", "Status"], ["ev", "Bewertung"]];
const val = (i: Info, k: Key): number | string => (k === "gs" ? gronosStatus(i.r) : k === "ev" ? ORD.indexOf(i) : k === "start" ? +i.r.start : i.r[k]);

export function Overview({ onOpen }: { onOpen: (id: number) => void }) {
  const [sort, setSort] = useState<{ k: Key; d: number }>({ k: "ev", d: 1 });
  // rows fade in once, on the first visit; sorting and coming back show them as they are
  const [animate] = useState(() => !isSeen("overview"));
  useEffect(() => markSeen("overview"), []);
  const [tip, setTip] = useState<{ x: number; y: number; id: number } | null>(null);

  const rows = useMemo(
    () => ORD.slice().sort((a, b) => { const x = val(a, sort.k), y = val(b, sort.k); return (x < y ? -1 : x > y ? 1 : 0) * sort.d; }),
    [sort],
  );
  const nMine = INFO.filter((i) => i.mine).length, nOpen = INFO.filter((i) => !i.fin).length, nFin = INFO.length - nOpen;
  const clickHead = (k: Key) => setSort((s) => (s.k === k ? { k, d: -s.d } : { k, d: 1 }));
  const move = (e: MouseEvent, id: number) => setTip({ x: Math.min(window.innerWidth - 380, e.clientX + 14), y: Math.min(window.innerHeight - 110, e.clientY + 16), id });
  const tipRow = tip && INFO.find((x) => x.r.id === tip.id)!;
  const tipInfo = tipRow && { i: tipRow, e: evalState(tipRow) };

  return (
    <>
      <div className="rh">
        <div>
          <div className="crumb">Anfragen</div>
          <h1>
            Netzanschlussanfragen<small>{INFO.length} Anfragen · Stand {fmt(TODAY)}</small>
          </h1>
        </div>
      </div>
      <div className="ov oa">
        <div className="ov-h">
          <div className="kp">
            <span><b>{INFO.length}</b>Anfragen</span>
            <span style={{ color: "#5aa9ff" }}><b style={{ color: "#5aa9ff" }}>{nMine}</b>warten auf dich</span>
            <span><b>{nOpen}</b>in Bewertung</span>
            <span><b>{nFin}</b>abgeschlossen</span>
          </div>
        </div>
        <div className="oa-h" role="row">
          {HEAD.map(([k, t, c]) => (
            <button key={k} type="button" className={`${c ?? ""} ${sort.k === k ? "on" : ""}`} onClick={() => clickHead(k)} aria-sort={sort.k === k ? (sort.d > 0 ? "descending" : "ascending") : undefined}>
              {t}{sort.k === k ? (sort.d > 0 ? " ↓" : " ↑") : ""}
            </button>
          ))}
        </div>
        <div className={animate ? "play" : undefined}>
          {rows.map((i, n) => {
            const e = evalState(i), d = n * 55 + 180, gs = gronosStatus(i.r);
            return (
              <div
                key={i.r.id}
                className={`oa-r rw ${i.mine ? "me" : ""}`}
                style={{ ["--rd" as string]: `${n * 55}ms` }}
                role="button"
                tabIndex={0}
                onMouseMove={(ev) => move(ev, i.r.id)}
                onMouseLeave={() => setTip(null)}
                onClick={() => { setTip(null); onOpen(i.r.id); }}
                onKeyDown={(ev) => { if (ev.key === "Enter") onOpen(i.r.id); }}
              >
                <span className="num r">{i.r.id}</span>
                <span className="nm">{i.r.name}</span>
                <span className="dimt">{i.r.kunde}</span>
                <span><span className="tg">{i.r.tech}</span></span>
                <span className="num r" style={{ color: "var(--fg)" }}>{i.r.mw}</span>
                <span className="dimt">{i.r.uw}</span>
                <span className="num">{fmt(i.r.start)}</span>
                <span>
                  <span className="gsn" title={`Status der Anfrage: ${gs} von 5`}>
                    {[1, 2, 3, 4, 5].map((k) => <i key={k} className={k <= gs ? "f" : ""} />)}
                    <b>{gs}</b>
                  </span>
                </span>
                <div className={`evs ${e.k}`}>
                  <div className="sg7">
                    {i.subs.map((x, k) => <i key={x.s.key} className={segCls(x)} style={{ ["--d" as string]: `${d + k * 40}ms` }} title={x.s.label} />)}
                  </div>
                  <div className="l"><b>{e.t}</b><span>{e.s}</span></div>
                </div>
              </div>
            );
          })}
        </div>
        <div className="ov-leg">
          <span className="g">
            <span className="sg7" style={{ width: 54 }}><i className="f" /><i className="f" /><i className="m" /><i className="l" /><i /></span>
            ein Segment je Sub-Kriterium: festgelegt · bei dir · bei anderen · offen
          </span>
          <span className="g" style={{ marginLeft: "auto" }}>Status ist der Bearbeitungsstatus der Anfrage, 1 bis 5</span>
        </div>
      </div>
      {tipInfo && tip && (
        <div className="ovtip on" style={{ left: tip.x, top: tip.y }}>
          <b>{tipInfo.i.r.name}</b> · Ticket {tipInfo.i.r.id}<br />
          {tipInfo.i.r.kunde} · {tipInfo.i.r.tech} · {tipInfo.i.r.mw} MW · {tipInfo.i.r.uw}<br />
          {tipInfo.e.t}{tipInfo.i.fin ? ", " + tipInfo.e.w : ""}
          {!tipInfo.i.fin && (
            <>
              <br />
              {(Object.keys(tipInfo.i.turns) as Role[]).map((k) => ROLES[k].name + ": " + tipInfo.i.turns[k]!.map((x) => SUB[x].label).join(", ")).join(" · ")}
            </>
          )}
        </div>
      )}
    </>
  );
}
