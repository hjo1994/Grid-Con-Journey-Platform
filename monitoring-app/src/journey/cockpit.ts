// Sub-criterion cockpit "Drei Spalten" with the scoring graph "Pfad · Karte"
// and the evaluation cockpit "Lesetisch" (mockup cockpit.js: graph(), P1,
// viewer(), score(), RATE.a).
import { ago, BY_ID, fmt, guidance, ME, ROLES, STATE, SUB, summarize, type CommentSummary, type Ev, type Guidance, type Req, type Role, type Similar, type Sub, type SubState } from "./data";
import { $, $$, act, esc, LANES, qt, RC, rk, rn, svgEl, vb, type Life } from "./ui";

export interface Ctx { key: string; sub: Sub; r: Req; st: SubState; sm: CommentSummary; gd: Guidance }
export const ctx = (id: number, key: string): Ctx => {
  const sub = SUB[key], r = BY_ID[id], st = r.subs[key];
  return { key, sub, r, st, sm: summarize(id, key), gd: guidance(id, key) };
};

/* ---------- scoring graph: roles as lanes, path with a light dot and a card ---------- */
interface GraphOpts {
  onStep?: (e: Ev, i: number) => void;
  onDone?: () => void;
  onSelect?: (e: Ev, i: number) => void;
  onNow?: () => void;
  nowLabel?: string;
  delay?: number;
}
type Pt = [number, number];

export function graph(host: HTMLElement, st: SubState, sub: Sub, o: GraphOpts = {}) {
  const steps = st.events.slice(), fut: { role: Role; now?: boolean }[] = [];
  if (st.turn) fut.push({ role: st.turn, now: true });
  sub.order.forEach((k) => { if (st.vals[k] === undefined && k !== st.turn) fut.push({ role: k }); });
  if (st.state !== "fertig" && st.turn !== "BL") fut.push({ role: "BL" });
  const n = steps.length + fut.length, W = Math.max(380, host.clientWidth || 800), LH = 42, Y0 = 26, X0 = 150;
  const DX = Math.min(128, (W - X0 - 70) / Math.max(1, n - 1)), H = Y0 + 4 * LH + 16;
  host.innerHTML = "";
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, class: "ckg m-pfad-karte m-pfad", role: "img", "aria-label": "Bewertungsverlauf nach Rolle" }, host);
  const pos = (r: Role, i: number): Pt => [X0 + 26 + i * DX, Y0 + LANES.indexOf(r) * LH];
  const band = svgEl("rect", { class: "band", x: 0, y: -(LH - 6) / 2, width: W, height: LH - 6, fill: "#fff", opacity: 0 }, svg);
  LANES.forEach((k, i) => {
    const y = Y0 + i * LH;
    svgEl("line", { x1: 0, x2: W, y1: y, y2: y, stroke: "var(--line2)", "stroke-width": 1 }, svg);
    svgEl("rect", { x: 0, y: y - 8, width: 3, height: 16, fill: RC[k] }, svg);
    svgEl("text", { x: 12, y: y + 4, "font-size": 12, fill: "var(--fg2)" }, svg).textContent = rn(k);
  });
  const pl = svgEl("g", {}, svg), fl = svgEl("g", {}, svg), nl = svgEl("g", {}, svg);
  const tm: number[] = [], at = (ms: number, f: () => void) => tm.push(window.setTimeout(f, ms));
  let raf = 0, endFx: (() => void) | null = null;
  function seg(a: Pt, b: Pt, cls: string, dur: number, par: Element) {
    const mx = (a[0] + b[0]) / 2;
    const d = a[1] === b[1] ? `M${a[0] + 13} ${a[1]} H${b[0] - 13}` : `M${a[0] + 13} ${a[1]} C${mx} ${a[1]} ${mx} ${b[1]} ${b[0] - 13} ${b[1]}`;
    const p = svgEl("path", { d, class: cls }, par);
    if (!dur) return;
    p.style.opacity = "0"; p.style.transition = "opacity .5s";
    requestAnimationFrame(() => requestAnimationFrame(() => (p.style.opacity = "1")));
  }
  function select(i: number) { $$<SVGGElement>(nl, ".cn").forEach((q) => q.classList.toggle("sel", +q.dataset.i! === i)); }
  function node(e: Ev, i: number) {
    const [x, y] = pos(e.role, i), c = RC[e.role];
    const g = svgEl("g", { class: "cn", "data-i": i, tabindex: 0 }, nl);
    svgEl("rect", { class: "halo", x: x - 19, y: y - 19, width: 38, height: 38, rx: 4, fill: e.type === "angefragt" ? "#e3b341" : c }, g);
    if (e.type === "angefragt") {
      svgEl("rect", { x: x - 10, y: y - 10, width: 20, height: 20, rx: 1.5, transform: `rotate(45 ${x} ${y})`, fill: "#0e1116", stroke: "#e3b341", "stroke-width": 1.5 }, g);
      svgEl("text", { x, y: y + 4.5, "text-anchor": "middle", "font-size": 13, "font-weight": 600, fill: "#e3b341", "font-family": "var(--f-mono)" }, g).textContent = "?";
    } else {
      const fin = e.type === "festgelegt";
      svgEl("rect", { x: x - 13, y: y - 13, width: 26, height: 26, rx: 3, fill: fin ? "#5fd38d" : "#0e1116", stroke: fin ? "#5fd38d" : c, "stroke-width": 1.5 }, g);
      svgEl("text", { x, y: y + 5, "text-anchor": "middle", "font-size": 14, "font-weight": 600, fill: fin ? "#0e1116" : "var(--fg)", "font-family": "var(--f-mono)" }, g).textContent = String(e.val);
      if (e.type === "geaendert") svgEl("text", { x: x - 20, y: y - 9, "text-anchor": "middle", "font-size": 10, fill: "#e3b341", "font-family": "var(--f-mono)", "text-decoration": "line-through" }, g).textContent = String(e.from);
    }
    svgEl("text", { x, y: H - 4, "text-anchor": "middle", "font-size": 9.5, fill: "var(--fg3)", "font-family": "var(--f-mono)" }, g).textContent = fmt(e.t) + " " + String(e.t.getHours()).padStart(2, "0") + ":" + String(e.t.getMinutes()).padStart(2, "0");
    g.addEventListener("click", () => { select(i); o.onSelect?.(e, i); });
    return g;
  }
  const arrive = (e: Ev, i: number) => { select(i); o.onStep?.(e, i); };
  const t0 = o.delay || 200;
  let tf = t0;
  if (steps.length) {
    // one continuous soft path: a light dot glides from rating to rating and rests on each
    const P = steps.map((e, i) => pos(e.role, i)), lens = [0];
    let d = `M${P[0][0]} ${P[0][1]}`;
    const path = svgEl("path", { class: "cpath", d }, pl) as SVGPathElement;
    for (let i = 1; i < P.length; i++) {
      const a = P[i - 1], b = P[i], hx = (b[0] - a[0]) / 2;
      d += ` C${a[0] + hx} ${a[1]} ${b[0] - hx} ${b[1]} ${b[0]} ${b[1]}`;
      path.setAttribute("d", d); lens.push(path.getTotalLength());
    }
    const L = Math.max(1, lens[lens.length - 1]);
    path.style.strokeDasharray = String(L); path.style.strokeDashoffset = String(L);
    const dot = svgEl("g", { class: "pdot" }, svg);
    svgEl("circle", { r: 11, fill: "#5aa9ff", opacity: 0.16 }, dot); svgEl("circle", { r: 3.2, fill: "#d6e9ff" }, dot);
    dot.style.opacity = "0"; svg.appendChild(nl);
    host.style.position = "relative";
    const card = host.appendChild(Object.assign(document.createElement("div"), { className: "gcard" }));
    const say = (e: Ev, i: number) => `<span class="n">${i + 1}/${steps.length}</span>${rk(e.role, "fill")}<b>${esc(ROLES[e.role].name)}</b> ${act(e)}${e.tag ? ` <span class="tagc">${esc(e.tag)}</span>` : ""}<span class="q">${qt(e)}</span>`;
    const showCard = (i: number) => {
      const e = steps[i], [x, y] = P[i], up = LANES.indexOf(e.role) >= 2, left = Math.min(Math.max(x - 40, 8), W - 328);
      card.style.setProperty("--c", RC[e.role]); card.classList.toggle("up", up); card.classList.add("on");
      card.style.transform = `translate(${left}px,${up ? y - 26 : y + 26}px)` + (up ? " translateY(-100%)" : "");
      const inn = card.firstChild as HTMLElement | null;
      if (!inn) { card.innerHTML = `<div>${say(e, i)}</div>`; return; }
      inn.style.opacity = "0";
      tm.push(window.setTimeout(() => { inn.innerHTML = say(e, i); inn.style.opacity = "1"; }, 220));
    };
    const focus = (i: number) => {
      const e = steps[i], [x, y] = P[i];
      $$(nl, ".cn").forEach((q) => q.classList.add("dimd"));
      band.setAttribute("fill", RC[e.role]); band.style.transform = `translateY(${y}px)`; band.style.opacity = "0.09";
      const ring = svgEl("rect", { class: "pring", x: x - 13, y: y - 13, width: 26, height: 26, rx: 3, fill: "none", stroke: e.type === "angefragt" ? "#e3b341" : RC[e.role], "stroke-width": 1 }, pl);
      tm.push(window.setTimeout(() => ring.remove(), 1500));
      node(e, i); arrive(e, i); showCard(i);
    };
    const prevSelect = o.onSelect;
    o.onSelect = (e, i) => { showCard(i); prevSelect?.(e, i); };
    const MOVE = 620, HOLD = 920, CY = MOVE + HOLD, total = (steps.length - 1) * CY + HOLD;
    const ez = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
    let s0 = 0, shown = 0;
    const fr = (now: number) => {
      s0 = s0 || now;
      const t = now - s0, tt = Math.min(t, total), k = Math.min(steps.length - 1, Math.floor(tt / CY)), r = tt - k * CY;
      const cur = r <= HOLD || k >= steps.length - 1 ? lens[k] : lens[k] + (lens[k + 1] - lens[k]) * ez((r - HOLD) / MOVE);
      path.style.strokeDashoffset = String(L - cur);
      const pt = P.length > 1 ? path.getPointAtLength(cur) : { x: P[0][0], y: P[0][1] };
      dot.setAttribute("transform", `translate(${pt.x} ${pt.y})`); dot.style.opacity = t > total ? "0" : "1";
      while (shown <= k) focus(shown++);
      if (t < total) raf = requestAnimationFrame(fr);
    };
    at(t0 + 250, () => (raf = requestAnimationFrame(fr)));
    tf = t0 + 250 + total + 150;
    endFx = () => { $$(nl, ".cn").forEach((q) => q.classList.remove("dimd")); band.style.opacity = "0"; card.classList.remove("on"); };
  }
  fut.forEach((f, j) => at(tf + j * 200, () => {
    const i = steps.length + j, [x, y] = pos(f.role, i), c = RC[f.role];
    const prev: Pt | null = i ? pos(j ? fut[j - 1].role : steps[i - 1].role, i - 1) : null;
    if (j === 0 && endFx) { endFx(); endFx = null; }
    if (prev) seg(prev, [x, y], "cfut", 300, fl);
    const g = svgEl("g", { class: "cn", style: "cursor:default" }, nl);
    if (f.now) {
      svgEl("rect", { class: "now", x: x - 17, y: y - 17, width: 34, height: 34, rx: 4, fill: "none", stroke: c, "stroke-width": 1 }, g);
      svgEl("rect", { x: x - 13, y: y - 13, width: 26, height: 26, rx: 3, fill: c }, g);
      svgEl("text", { x, y: y + 3.5, "text-anchor": "middle", "font-size": 9, "font-weight": 700, fill: "#0e1116", "font-family": "var(--f-mono)" }, g).textContent = o.nowLabel || (f.role === ME ? "DU" : "ZUG");
      if (o.onNow) { g.classList.add("zug"); g.style.cursor = "pointer"; g.addEventListener("click", o.onNow); }
      svgEl("text", { x, y: H - 4, "text-anchor": "middle", "font-size": 9.5, fill: c, "font-family": "var(--f-mono)" }, g).textContent = "am Zug";
    } else {
      svgEl("rect", { x: x - 12, y: y - 12, width: 24, height: 24, rx: 3, fill: "#0e1116", stroke: "#5b6675", "stroke-dasharray": "2 3" }, g);
      svgEl("text", { x, y: y + 3.5, "text-anchor": "middle", "font-size": 8.5, fill: "var(--fg3)", "font-family": "var(--f-mono)" }, g).textContent = f.role === "BL" ? "fest" : "…";
    }
  }));
  at(tf + fut.length * 200 + 150, () => {
    if (endFx) { endFx(); endFx = null; }
    select(-1); o.onDone?.();
  });
  return { stop() { tm.forEach(clearTimeout); cancelAnimationFrame(raf); }, select };
}

/* ---------- shared pieces ---------- */
export function head(c: Ctx) {
  const { sub, st } = c, s = st.state, cls = s === "fertig" ? "ok" : s === "offen" ? "idle" : "";
  const roles: Role[] = [...sub.order, "BL"];
  return `<div class="ck-h"><div><span class="lab">SUB-KRITERIUM ${sub.label} · MAX ${sub.max}</span><h3>${esc(sub.name)}</h3><p class="q">${esc(sub.q)}</p></div>
    <div class="ck-turn"><span class="st ${cls}">${esc(STATE[s].label)}</span>${st.turn ? `<span>Am Zug: <b style="color:${RC[st.turn]}">${esc(rn(st.turn))}</b>${st.since ? " · " + ago(st.since) : ""}</span>` : st.final != null ? "<span>Bewertung steht fest</span>" : ""}</div>
    <div class="ck-vals">${roles.map((k) => `<div class="${st.turn === k ? "turn" : ""}" style="--c:${RC[k]}"><i>${k}</i><b>${k === "BL" ? (st.final ?? "–") : (st.vals[k] ?? "–")}</b></div>`).join("")}</div></div>`;
}
const gbox = () => `<div class="ck-g"><div class="ck-gl"><span class="ck-cap">Bewertungsverlauf</span><button class="ck-re" type="button">↻ Nochmal aufbauen</button></div><div class="gh"></div></div>`;
const sum3 = (sm: CommentSummary) => `<div class="sum3">${([["ag", "Einig", sm.agree], ["di", "Strittig", sm.dispute], ["op", "Offen", sm.open]] as const).map(([k, l, a]) => a.map((x) => `<div class="it rv late"><span class="k ${k}">${l}</span><span>${esc(x.text)}<span class="rs">${x.roles.map((r) => rk(r)).join("")}</span></span></div>`).join("")).join("") || '<div class="it rv late"><span class="k">–</span><span class="dim">Noch keine Kommentare zum Zusammenfassen.</span></div>'}</div>`;
const meta = (q: Similar) => `<span class="meta">${q.req.tech} · ${q.req.mw} MW · ${esc(q.req.uw)}</span>`;
const whys = (q: Similar) => `<span class="ws">${q.why.map((w) => `<span class="why">${esc(w)}</span>`).join("")}</span>`;
const none = (t: string) => `<p class="dim" style="margin:6px 0;font-size:13px">${t}</p>`;
const late = (root: ParentNode, life: Life, base = 0, gap = 130) => $$(root, ".late").forEach((n, i) => life.timeout(() => n.classList.add("on"), base + i * gap));

/* ---------- 1 · Drei Spalten ---------- */
export const P1 = {
  html(c: Ctx) {
    const { sub, st, sm, gd } = c;
    const voices = ([...sub.order, "BL"] as Role[]).map((k) => {
      const ev = st.events.filter((e) => e.role === k), last = ev[ev.length - 1];
      if (!last) return `<div class="voice none rv late" style="--c:${RC[k]}"><div class="vh">${rk(k)}${esc(rn(k))}</div><p class="tx">${k === "BL" ? "Legt fest, sobald alle Bewertungen vorliegen." : st.turn === k ? "Ist am Zug, noch keine Bewertung." : "Noch keine Bewertung."}</p></div>`;
      return `<div class="voice rv" data-role="${k}" style="--c:${RC[k]}"><div class="vh">${rk(k)}${esc(rn(k))}${last.tag ? `<span class="tagc">${esc(last.tag)}</span>` : ""}${vb(k === "BL" ? st.final : st.vals[k])}</div><p class="tx">${qt(last)}</p>
        <div class="hist">${ev.map((e) => fmt(e.t) + " " + (e.type === "geaendert" ? e.from + "→" + e.val : e.type === "angefragt" ? "? an " + e.to : e.val)).join("  ·  ")}</div></div>`;
    }).join("");
    return gbox() + `<div class="ck-b p1"><div><span class="ck-cap">Stimmen der Beteiligten</span>${voices}</div>
      <div><span class="aik">Zusammenfassung</span><p class="tldr rv late">${esc(sm.tldr)}</p>${sum3(sm)}</div>
      <div><span class="ck-cap">Ähnliche Anfragen</span>${gd.sim.length ? `<div class="sugbox rv late"><span class="big">${gd.suggest}</span><b>Vorschlag aus ${gd.sim.length} ähnlichen Fällen</b><p>${esc(gd.because)}</p></div>` + gd.sim.slice(0, 4).map((q) => `<div class="simc rv late">${vb(q.val, q.val === gd.suggest ? "sug" : "")}<div class="nm">${esc(q.req.name)} ${meta(q)}</div><div class="qt">„${esc(q.quote)}“ ${q.by ? rk(q.by) : ""}</div>${whys(q)}</div>`).join("") : none("Keine vergleichbaren Anfragen gefunden.")}</div></div>`;
  },
  run(root: ParentNode, life: Life) {
    return {
      onStep: (e: Ev) => { root.querySelector(`.voice[data-role="${e.role}"]`)?.classList.add("on"); },
      onDone: () => late(root, life),
    };
  },
};

/* ---------- documents of the evaluation cockpit ---------- */
interface Highlight { role: Role; val: number; note: string }
interface Section { t: string; p: number; x: string }
interface Station extends Highlight { i: number; si: number; sec: Section; text: string; pre: string; post: string }
interface Doc { id: string; name: string; short: string; kind: string; date: string; pages: number; neu?: boolean; rel: number; why: string; secs: Section[]; hl: Highlight[]; st: Station[] }

function prep(d: Omit<Doc, "st">): Doc {
  const st: Station[] = [];
  d.secs.forEach((s, si) => s.x.replace(/\[\[(\d)\|([^\]]+)\]\]/g, (m, i: string, tx: string, off: number) => {
    st[+i] = { ...d.hl[+i], i: +i, si, sec: s, text: tx, pre: s.x.slice(0, off).replace(/\[\[\d\||\]\]/g, ""), post: s.x.slice(off + m.length).replace(/\[\[\d\||\]\]/g, "") };
    return m;
  }));
  return { ...d, st };
}
// Hand-written documents for the focus case Projekt-G02 / B3
const DOCS_B3: Doc[] = ([
  { id: "gv", name: "Gestattungsverträge_Übersicht.pdf", short: "Gestattungsverträge", kind: "Nachreichung Kunde", date: "11.11.", pages: 6, neu: true, rel: 96, why: "Neu seit deiner Bewertung, von Netzplanung zitiert",
    secs: [{ t: "1 Zusammenfassung", p: 1, x: "Für die geplante Kabeltrasse zum UW Nord-3 sind insgesamt 20 Flurstücke betroffen. [[0|Für 14 der 20 Flurstücke liegen unterschriebene Gestattungsverträge vor (70 %).]] Die übrigen Verträge befinden sich in Abstimmung mit den Eigentümern." },
      { t: "2 Flurstücksliste", p: 2, x: "Gemarkung Nordfeld, Flur 3: Flurstücke 112 bis 119 unterschrieben. Gemarkung Nordfeld, Flur 4: Flurstücke 20 bis 25 unterschrieben. Die Verträge enthalten die Zustimmung zur Eintragung einer beschränkten persönlichen Dienstbarkeit." },
      { t: "3 Offene Eigentümer", p: 4, x: "[[1|Mit zwei Eigentümern (Flurstücke 131 und 140) laufen noch Verhandlungen über die Höhe der Entschädigung.]] Für vier Flurstücke der Gemeinde ist der Ratsbeschluss terminiert. [[2|Der Kunde sagt den Abschluss aller restlichen Verträge bis zum 30.11. zu.]]" }],
    hl: [{ role: "NP", val: 1, note: "70 % sind gesichert. Das reicht aus meiner Sicht für 1." }, { role: "NP", val: 1, note: "Das sind die zwei Eigentümer, die bei dir zur 0 geführt haben." }, { role: "FI", val: 1, note: "Zusage mit Datum, das Risiko ist überschaubar." }] },
  { id: "tp", name: "Trassenplan_Rev3.pdf", short: "Trassenplan", kind: "Antragsunterlage", date: "24.10.", pages: 12, rel: 74, why: "Grundlage der ersten Bewertungen",
    secs: [{ t: "2 Trassenverlauf", p: 3, x: "Die Kabeltrasse verläuft vom Übergabepunkt des Windparks über 4,2 km in nordöstlicher Richtung zum UW Nord-3. [[0|Der Verlauf ist mit dem Netzbetreiber abgestimmt und technisch festgelegt.]] Querungen: eine Kreisstraße und ein Entwässerungsgraben." },
      { t: "4 Wegerechte", p: 8, x: "[[1|Die Sicherung der Wegerechte erfolgt über Gestattungsverträge und ist zum Zeitpunkt der Einreichung in Arbeit.]] Die Dienstbarkeiten werden nach Vertragsschluss eingetragen." },
      { t: "5 Kostenschätzung", p: 10, x: "Die Kosten der Trasse werden auf 1,9 Mio. € geschätzt. [[2|Entschädigungen für Wegerechte sind mit 180 T€ berücksichtigt.]] Reserven für Umverlegungen sind nicht enthalten." }],
    hl: [{ role: "NP", val: 2, note: "Deshalb zuerst 2: Die Trasse steht technisch." }, { role: "NP", val: 1, note: "Später auf 1 korrigiert, die Wegerechte waren noch offen." }, { role: "FI", val: 1, note: "Das Budget für Entschädigungen ist eingeplant." }] },
  { id: "we", name: "Wegerechte_Entwurf.pdf", short: "Wegerechte Entwurf", kind: "Antragsunterlage", date: "28.10.", pages: 4, rel: 58, why: "Grundlage deiner 0 vom 03.11.",
    secs: [{ t: "1 Stand der Verträge", p: 1, x: "[[0|Die Gestattungsverträge liegen als Entwurf vor und sind noch nicht unterzeichnet.]] Die Abstimmung mit den Eigentümern wurde begonnen." },
      { t: "2 Fehlende Eigentümer", p: 3, x: "[[1|Zwei Eigentümer konnten bislang nicht erreicht werden.]] Ein Termin mit der Gemeinde steht noch aus." }],
    hl: [{ role: "RE", val: 0, note: "Deine Markierung: nur ein Entwurf, daher 0." }, { role: "RE", val: 0, note: "Deine Markierung: zwei Eigentümer fehlen." }] },
] satisfies Omit<Doc, "st">[]).map(prep);

function genDocs(id: number, key: string): Doc[] {
  const s = SUB[key], ev = BY_ID[id].subs[key].events.filter((e) => e.type === "bewertet" || e.type === "geaendert"), slug = s.name.replace(/[^A-Za-zÄÖÜäöüß]+/g, "_");
  const mk = (did: string, name: string, short: string, kind: string, date: string, pages: number, rel: number, why: string, evs: Ev[]) => prep({
    id: did, name, short, kind, date, pages, rel, why, hl: evs.map((e) => ({ role: e.role, val: e.val!, note: e.text || `Grundlage für die Bewertung ${e.val}.` })),
    secs: evs.length
      ? evs.map((e, i) => ({ t: `${i + 1} ${e.tag || s.name}`, p: Math.min(pages, 1 + i * 2), x: `Dieser Abschnitt beschreibt den Stand zu „${s.name}“. [[${i}|${e.tag ? e.tag + ": " : ""}${s.levels[Math.min(e.val!, s.levels.length - 1)]}.]] Die zugehörigen Nachweise liegen dem Antrag als Anlage bei.` }))
      : [{ t: "1 " + s.name, p: 1, x: `Dieser Abschnitt beschreibt den Stand zu „${s.name}“. Bisher hat hier niemand eine Stelle markiert.` }],
  });
  return [mk("d1", `Antrag_${slug}.pdf`, "Antrag", "Antragsunterlage", "24.10.", 8, 90, ev.length ? "Von den meisten Bewertungen zitiert" : "Hauptunterlage zu diesem Sub-Kriterium", ev.filter((_, i) => i % 2 === 0)),
    mk("d2", `Nachweise_${slug}.pdf`, "Nachweise", "Anlage", "28.10.", 5, 62, "Belege zu den Angaben im Antrag", ev.filter((_, i) => i % 2 === 1))];
}
const dcache: Record<string, Doc[]> = {};
const docsOf = (id: number, key: string) => (key === "B3" && id === 4902 ? DOCS_B3 : (dcache[id + ":" + key] = dcache[id + ":" + key] || genDocs(id, key)));

const hlc = (d: Doc) => {
  const n: Partial<Record<Role, number>> = {};
  d.hl.forEach((h) => (n[h.role] = (n[h.role] || 0) + 1));
  return (Object.keys(n) as Role[]).map((k) => rk(k)).join("") + ` <span>${d.hl.length ? d.hl.length + " markierte Stelle" + (d.hl.length > 1 ? "n" : "") : "keine markierten Stellen"}</span>`;
};
const by = (h: Highlight) => `${rk(h.role, "fill")}<b>${esc(ROLES[h.role].name)}</b> markiert für Bewertung ${vb(h.val, "sm")}`;

/* Document with a guided tour through the marked passages */
function viewer(host: HTMLElement, d: Doc) {
  const mk = (s: Section) => esc(s.x).replace(/\[\[(\d)\|([^\]]+)\]\]/g, (_m, i: string, tx: string) => `<mark data-h="${i}" style="--c:${RC[d.hl[+i].role]}">${tx}</mark>`);
  host.innerHTML = `<div class="dv"><div class="dv-h"><b>${esc(d.name)}</b><span class="meta">${d.kind} · ${d.date} · ${d.pages} S.</span>
      <span class="dv-ctl"><button type="button" data-a="prev" title="Vorherige Stelle">◂</button><span class="dv-n"></span><button type="button" data-a="next" title="Nächste Stelle">▸</button><button type="button" data-a="play" title="Führung anhalten oder fortsetzen">❚❚</button></span></div><div class="dv-prog"><i></i></div>
    <div class="dv-b"><div class="dv-page">${d.secs.map((s, i) => `<section data-s="${i}"><h5><span>${esc(s.t)}</span><span>S. ${s.p}</span></h5><p>${mk(s)}</p></section>`).join("")}</div><div class="dv-side"><div class="dv-note"></div></div></div></div>`;
  const page = $(host, ".dv-page"), note = $(host, ".dv-note"), nEl = $(host, ".dv-n"), prog = $(host, ".dv-prog i"), pb = $(host, '[data-a="play"]');
  const tms: number[] = [];
  let cur = -1, tm = 0, playing = true;
  const HOLD = 2600;
  function go(i: number) {
    clearTimeout(tm);
    if (i < 0 || i >= d.st.length) return;
    cur = i;
    const h = d.st[i], m = $(page, `mark[data-h="${i}"]`);
    $$(page, "mark").forEach((x) => { const k = +x.dataset.h!; x.classList.toggle("cur", k === i); if (k < i) x.classList.add("seen"); });
    $$(page, "section").forEach((s) => s.classList.toggle("cur", +s.dataset.s! === h.si));
    const top = Math.max(0, m.offsetTop - 96);
    page.scrollTo({ top, behavior: "smooth" });
    note.style.setProperty("--c", RC[h.role]); note.classList.remove("on");
    tms.push(window.setTimeout(() => { note.innerHTML = `<div>${by(h)}</div><p>„${esc(h.note)}“</p>`; note.style.transform = `translateY(${Math.max(8, m.offsetTop - top - 6)}px)`; note.classList.add("on"); }, 240));
    nEl.textContent = `Stelle ${i + 1}/${d.st.length}`;
    prog.style.transition = "none"; prog.style.width = (i / d.st.length * 100) + "%";
    if (playing) {
      requestAnimationFrame(() => requestAnimationFrame(() => { prog.style.transition = `width ${HOLD}ms linear`; prog.style.width = ((i + 1) / d.st.length * 100) + "%"; }));
      tm = window.setTimeout(() => { if (i + 1 < d.st.length) go(i + 1); else { playing = false; pb.textContent = "↻"; } }, HOLD);
    }
  }
  $(host, '[data-a="prev"]').addEventListener("click", () => { playing = false; pb.textContent = "▶"; go(Math.max(0, cur - 1)); });
  $(host, '[data-a="next"]').addEventListener("click", () => { playing = false; pb.textContent = "▶"; go(Math.min(d.st.length - 1, cur + 1)); });
  pb.addEventListener("click", () => { playing = !playing; pb.textContent = playing ? "❚❚" : "▶"; if (playing) go(cur + 1 < d.st.length ? cur : 0); else { clearTimeout(tm); prog.style.transition = "none"; } });
  $$(page, "mark").forEach((m) => m.addEventListener("click", () => { playing = false; pb.textContent = "▶"; go(+m.dataset.h!); }));
  if (d.st.length) tm = window.setTimeout(() => go(0), 500);
  else { nEl.textContent = "Keine Stellen"; note.innerHTML = '<p style="color:var(--fg2)">In diesem Dokument hat noch niemand eine Stelle markiert.</p>'; note.style.transform = "translateY(12px)"; note.classList.add("on"); }
  return { stop() { clearTimeout(tm); tms.forEach(clearTimeout); } };
}

/* ---------- 3 · evaluation cockpit "Lesetisch" ---------- */
export function lesetisch(box: HTMLElement, id: number, key: string, life: Life) {
  const c = ctx(id, key), DOCS = docsOf(id, key), role: Role = c.st.turn || ME, others = c.sub.order.filter((k) => k !== role);
  const zhead = `<div class="zr-h"><div><span class="lab" style="color:${RC[role]}">BEWERTUNGS-COCKPIT · ${role === ME ? "DU BIST AM ZUG" : "AM ZUG: " + ROLES[role].name.toUpperCase()}</span><h3>${c.sub.label} ${esc(c.sub.name)} ${role === "BL" ? "festlegen" : "bewerten"}</h3></div>
    ${c.st.pending ? `<div class="ask"><b>${esc(ROLES[c.st.pending.role].name)}</b> bittet ${role === ME ? "dich" : ROLES[role].name} um erneute Prüfung: „${esc(c.st.pending.text)}“</div>` : ""}</div>`;
  box.innerHTML = zhead + `<div class="zA"><div class="zdocs"><span class="ck-cap">Relevante Dokumente</span>${DOCS.map((d) => `<button type="button" class="dcard rv" data-d="${d.id}" style="--w:${d.rel}%">${d.neu ? "<em>NEU</em>" : ""}<span class="nm">${esc(d.name)}</span><span class="meta">${d.kind} · ${d.date} · ${d.pages} S.</span><span class="rel"><i></i></span><span class="dw">${esc(d.why)}</span><span class="hlc">${hlc(d)}</span></button>`).join("")}</div><div class="zview"></div><div class="zscore"></div></div>`;
  let v: { stop(): void } | null = null;
  const open = (did: string) => { v?.stop(); $$(box, ".dcard").forEach((b) => b.classList.toggle("sel", b.dataset.d === did)); v = viewer($(box, ".zview"), DOCS.find((d) => d.id === did)!); };
  $$(box, ".dcard").forEach((b) => b.addEventListener("click", () => open(b.dataset.d!)));
  $$(box, ".dcard").forEach((n, i) => life.timeout(() => n.classList.add("on"), 150 + i * 120));
  score($(box, ".zscore"), c, role, others, life);
  life.timeout(() => open(DOCS[0].id), 750);
  life.add(() => v?.stop());
}

/* Choosing the rating, with what follows from it */
function score(host: HTMLElement, c: Ctx, role: Role, others: Role[], life: Life) {
  const { sub, st } = c, n = sub.max + 1;
  host.innerHTML = `<div class="sc" style="--n:${n}"><span class="ck-cap">${role === "BL" ? "Festlegung" : role === ME ? "Deine Bewertung" : "Bewertung"} für ${sub.label}</span>
    <div class="sc-opts">${[...Array(n).keys()].map((v) => `<button type="button" class="sc-o rv ${v === c.gd.suggest ? "sug" : ""}" data-v="${v}"><b>${v}</b><span>${esc(sub.levels[v])}</span>
      <span class="who">${others.filter((k) => st.vals[k] === v).map((k) => rk(k)).join("")}${role !== "BL" && st.vals[role] === v ? rk(role, "fill") + (role === ME ? " du bisher" : " bisher") : ""}</span></button>`).join("")}</div><div class="sc-out"></div></div>`;
  const out = $(host, ".sc-out");
  $$(host, ".sc-o").forEach((b) => b.addEventListener("click", () => {
    const v = +b.dataset.v!;
    $$(host, ".sc-o").forEach((x) => x.classList.toggle("on", x === b));
    const rated = others.filter((k) => st.vals[k] !== undefined), same = rated.every((k) => st.vals[k] === v), diff = rated.filter((k) => st.vals[k] !== v);
    out.innerHTML = `<div class="cq ${same ? "" : "dv2"}">${role === "BL" ? `Damit ist ${sub.label} mit ${v} festgelegt und abgeschlossen.${diff.length ? " Abweichend bewertet hatten " + diff.map((k) => ROLES[k].name + " (" + st.vals[k] + ")").join(" und ") + "." : ""}` : !rated.length ? `Das ist die erste Bewertung für ${sub.label}. Danach sind die anderen Rollen am Zug.` : same ? `Damit stehen alle bisherigen Bewertungen bei ${v}. ${sub.label} geht nach der letzten Bewertung zur Festlegung an die Bewertungsleitung.` : `Das weicht von ${diff.map((k) => ROLES[k].name + " (" + st.vals[k] + ")").join(" und ")} ab. Die Bewertungsleitung entscheidet mit deiner Begründung.`}</div>
      <textarea placeholder="${c.key === "B3" && c.r.id === 4902 ? "Begründung, zum Beispiel: 70 % der Verträge liegen vor, Rest bis 30.11. zugesagt." : "Kurze Begründung für die Auswahl"}"></textarea><button type="button" class="sc-go">${role === "BL" ? v + " festlegen" : "Bewertung " + v + " abgeben"}</button>`;
    out.classList.add("on");
    $(out, ".sc-go").addEventListener("click", (e) => { const t = e.currentTarget as HTMLElement; t.classList.add("done"); t.textContent = "✓ Abgegeben (Demo, nicht gespeichert)"; });
  }));
  $$(host, ".sc-o").forEach((b, i) => life.timeout(() => b.classList.add("shown"), 500 + i * 110));
}
