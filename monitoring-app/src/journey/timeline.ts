// Criteria timeline in the "Graphit" design with the calendar build-up
// "Spur" (mockup journey.html: timeline(r, 'd', 'kal-spur') and initTl).
import { evText, fmt, fmtT, ago, ME, ROLES, SUBS, TODAY, type Ev, type Req, type Role, type Sub } from "./data";
import { $, $$, esc, hover, tip, type Life } from "./ui";

const tnum = (x: number, y: number, t: string | number | undefined, fill: string, fs = 13) =>
  `<text x="${x}" y="${y + fs * 0.35}" text-anchor="middle" font-size="${fs}" font-weight="600" font-family="var(--f-mono)" fill="${fill}">${t}</text>`;
const tsq = (x: number, y: number, s: number, a: string) => `<rect x="${x - s / 2}" y="${y - s / 2}" width="${s}" height="${s}" rx="1.5" ${a}/>`;

// Theme "d" (Graphit)
const N: Record<Role, string> = { NP: "#5aa9ff", RE: "#ff9466", FI: "#5fd38d", BL: "#b494ff" };
const TH = {
  line: () => "#4a5568",
  lw: 1.5,
  okText: "#5fd38d",
  wait: (me: boolean) => (me ? "#5aa9ff" : "#5b6675"),
  labY: 22,
  dot: (x: number, y: number, e: Pick<Ev, "role" | "type" | "val">) =>
    e.type === "angefragt"
      ? `<rect x="${x - 6}" y="${y - 6}" width="12" height="12" transform="rotate(45 ${x} ${y})" fill="#0e1116" stroke="${N[e.role]}" stroke-width="1.5"/>` + tnum(x, y - 16, "?", N[e.role], 10.5)
      : e.type === "festgelegt"
        ? tsq(x, y, 16, `fill="#5fd38d"`) + tnum(x, y - 17, e.val, "#5fd38d", 12)
        : tsq(x, y, 12, `fill="#0e1116" stroke="${N[e.role]}" stroke-width="2"`) + tnum(x, y - 15, e.val, N[e.role], 11.5),
  legend: [
    [{ role: "NP", val: 1 }, ROLES.NP.name], [{ role: "RE", val: 1 }, ROLES.RE.name], [{ role: "FI", val: 1 }, ROLES.FI.name],
    [{ role: "BL", val: 2, type: "festgelegt" }, "Festlegung"], [{ role: "NP", type: "angefragt" }, "Rückfrage"],
  ] as [Partial<Ev> & { role: Role }, string][],
};

interface Geo { W: number; L: number; RP: number; xt: number; t0: number; t1: number; tips: Ev[] }

export function timelineHtml(r: Req): { html: string; geo: Geo } {
  const W = 1220, L = 256, RP = 160, RH = 62, T = 56, H = T + 7 * RH + 8;
  const all = SUBS.flatMap((sb) => r.subs[sb.key].events.map((e) => +e.t));
  const t0 = new Date(Math.min(...all, +TODAY - 5 * 864e5)); t0.setHours(0, 0, 0, 0);
  const t1 = +TODAY;
  const x = (t: number) => L + (t - +t0) / (t1 - +t0) * (W - L - RP), xt = x(t1);
  let grid = "";
  const nDays = Math.ceil((t1 - +t0) / 864e5);
  for (let d = 0; d <= nDays; d++) {
    const tt = new Date(+t0 + d * 864e5), xx = x(+tt), x2 = Math.min(xt, x(+tt + 864e5));
    if (xx >= xt) break;
    if (tt.getDay() === 0 || tt.getDay() === 6) grid += `<rect x="${xx}" y="${T - 6}" width="${x2 - xx}" height="${H - T}" fill="var(--sunk)"/>`;
    if (d % 2 === 0 && xx < xt - 40) grid += `<text x="${xx}" y="${T - 14}" font-size="10.5" font-family="var(--f-mono)" fill="var(--fg3)">${fmt(tt)}</text><line x1="${xx}" x2="${xx}" y1="${T - 8}" y2="${H - 6}" stroke="var(--line2)"/>`;
  }
  const tips: Ev[] = [];
  const rows = SUBS.map((sb: Sub, i) => {
    const st = r.subs[sb.key], y = T + i * RH + RH / 2, ev = st.events;
    let px = -99;
    const pts = ev.map((e) => { const xx = Math.max(x(+e.t), px + 28); px = xx; return [xx, e] as const; });
    const x0 = pts.length ? pts[0][0] : L + 4, xl = pts.length ? pts[pts.length - 1][0] : L + 4;
    const dots = pts.map(([xx, e]) => {
      const fin = e.type === "festgelegt";
      tips.push(e);
      return `<g class="ev" data-x="${xx}" data-tip="${tips.length - 1}" data-fin="${fin ? 1 : 0}" data-rate="${e.type === "angefragt" ? 0 : 1}"><rect class="ping" x="${xx - 8}" y="${y - 8}" width="16" height="16" fill="none" stroke="var(--accent)" stroke-width="1"/>${TH.dot(xx, y, e)}<text x="${xx}" y="${y + TH.labY + 3}" text-anchor="middle" font-size="8" letter-spacing=".5" font-family="var(--f-mono)" fill="var(--fg3)">${fin ? "fest" : e.role}</text></g>`;
    }).join("");
    const me = st.turn === ME;
    const end = st.turn
      ? `<g class="end"><rect x="${xt - 14}" y="${y - 10}" width="28" height="20" rx="2" fill="${me ? "var(--accent)" : "var(--panel)"}" stroke="${me ? "var(--accent)" : "var(--fg3)"}" stroke-width="1.5"/><text x="${xt}" y="${y + 3.5}" text-anchor="middle" font-size="9.5" font-weight="600" font-family="var(--f-mono)" fill="${me ? "var(--panel)" : "var(--fg)"}">${st.turn}</text>
      <text x="${xt + 24}" y="${y - 2}" font-size="12.5" font-weight="600" fill="${me ? "var(--accent)" : "var(--fg)"}">${me ? "Du bist dran" : ROLES[st.turn].name}</text><text x="${xt + 24}" y="${y + 13}" font-size="11" fill="var(--fg3)">wartet ${ago(st.since)}</text></g>`
      : `<g class="ev" data-x="${xl + 1}" data-rate="0" data-fin="0"><text x="${xl + 26}" y="${y + 4}" font-size="12.5" fill="${TH.okText}" font-weight="600">✓ festgelegt</text></g>`;
    return `<g class="row" data-sub="${sb.key}"><rect class="hit" x="4" y="${y - RH / 2 + 3}" width="${W - 8}" height="${RH - 6}" rx="2"/>
      <text x="16" y="${y - 2}" font-size="13.5" font-weight="600" fill="var(--fg)"><tspan font-family="var(--f-mono)" font-size="11" fill="var(--fg3)" font-weight="500">${sb.label}  </tspan>${esc(sb.name)}</text><text class="cnt" data-sub="${sb.key}" x="16" y="${y + 14}" font-size="10.5" fill="var(--fg3)"></text>
      <line x1="${L}" x2="${xt}" y1="${y}" y2="${y}" stroke="var(--line2)" stroke-width="1"/>
      <line class="ln" data-x0="${x0}" data-xl="${xl}" x1="${x0}" x2="${x0}" y1="${y}" y2="${y}" stroke="${TH.line()}" stroke-width="${pts.length > 1 ? TH.lw : 0}"/>
      ${st.turn ? `<line class="wt wait" data-a="${xl + (pts.length ? 16 : 0)}" x1="${xl + (pts.length ? 16 : 0)}" x2="${xl}" y1="${y}" y2="${y}" stroke="${TH.wait(me)}" stroke-width="1.5"/>` : ""}${dots}${end}<rect class="tip" x="-1.5" y="${y - 7}" width="3" height="14" fill="var(--accent)"/></g>`;
  }).join("");
  const leg = TH.legend.map(([e, lab]) => `<span><svg width="34" height="34" viewBox="-22 -24 44 44">${TH.dot(0, 0, { type: "bewertet", ...e })}</svg>${lab}</span>`).join("");
  const html = `<div class="box tl2 th-d fx-kal-spur fx-kalender" data-fx="kal-spur"><div class="tlhead"><button class="btn pri tlplay" type="button">❚❚ Pause</button><div class="tlstat"><b class="tldate">–</b><span class="tlsum dim"></span></div></div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Zeitstrahl der Bewertung"><defs><linearGradient id="beamg" x1="0" x2="1"><stop offset="0" stop-color="#5aa9ff" stop-opacity="0"/><stop offset="1" stop-color="#5aa9ff" stop-opacity=".3"/></linearGradient></defs>${grid}<rect class="dayc" x="0" y="${T - 6}" width="${(xt - L) / ((t1 - +t0) / 864e5)}" height="${H - T}" fill="var(--accent)" opacity=".08"/><text class="wm" x="${xt - 24}" y="${H - 36}" text-anchor="end" font-size="150" font-weight="600" letter-spacing="-4" font-family="var(--f-mono)" fill="var(--fg)" opacity=".055"></text>
    <g class="ph"><rect class="beam" x="-170" y="${T - 6}" width="170" height="${H - T}" fill="url(#beamg)"/><line y1="${T - 28}" y2="${H - 6}" stroke="var(--accent)" stroke-width="1.25"/><rect x="-25" y="${T - 48}" width="50" height="20" rx="2" fill="var(--accent)"/><text class="pht phl" y="${T - 35}" text-anchor="middle" font-size="11" font-weight="600" font-family="var(--f-mono)"></text></g>${rows}</svg>
    <div class="tlsl" style="padding-left:${L / W * 100}%;padding-right:${RP / W * 100}%"><input type="range" class="tlr" min="0" max="1000" value="0" aria-label="Zeitpunkt"></div>
    <div class="tlleg">${leg}</div></div>`;
  return { html, geo: { W, L, RP, xt, t0: +t0, t1, tips } };
}

// Player: the day column with its fading trail sweeps from the first day to
// today once the timeline is visible; button and slider control it.
export function initTimeline(host: HTMLElement, c: Geo, life: Life) {
  let raf = 0;
  life.add(() => cancelAnimationFrame(raf));
  const sl = $<HTMLInputElement>(host, ".tlr"), btn = $<HTMLButtonElement>(host, ".tlplay");
  const ph = $(host, ".ph"), span = c.xt - c.L;
  const rows = $$(host, ".row").map((g) => ({
    g, evs: $$<SVGGElement>(g, ".ev"), ln: g.querySelector<SVGLineElement>(".ln"), wt: g.querySelector<SVGLineElement>(".wt"),
    end: g.querySelector(".end"), tipEl: g.querySelector<SVGRectElement>(".tip"), cnt: $(g, ".cnt"),
  }));
  const evs = rows.flatMap((r) => r.evs);
  const DUR = 3600;
  const gpx = (p: number) => c.L + span * p;
  let P = 0, playing = false;
  const atEnd = () => P >= 1 - 1e-6;
  function set(p: number) {
    P = Math.max(0, Math.min(1, p));
    const g = gpx(P), end = atEnd();
    rows.forEach((r) => {
      const px = g, done = px >= c.xt - 0.5;
      r.evs.forEach((e) => e.classList.toggle("on", +e.dataset.x! <= px + 0.5));
      if (r.ln) { r.ln.setAttribute("x2", String(Math.max(+r.ln.dataset.x0!, Math.min(+r.ln.dataset.xl!, px)))); r.ln.style.opacity = px > +r.ln.dataset.x0! ? "1" : "0"; }
      if (r.wt) { const a = +r.wt.dataset.a!; r.wt.style.opacity = px > a + 6 ? "1" : "0"; r.wt.setAttribute("x2", String(Math.max(a, px - (done ? 18 : 0)))); }
      if (r.end) r.end.classList.toggle("on", done);
      if (r.tipEl) { r.tipEl.setAttribute("transform", `translate(${px} 0)`); r.tipEl.style.opacity = px > c.L + 1 && !done ? "1" : "0"; }
      const n = r.evs.filter((e) => e.classList.contains("on") && e.dataset.rate === "1").length;
      r.cnt.textContent = n ? `${n} Bewertung${n === 1 ? "" : "en"}` : "noch nichts";
    });
    ph.setAttribute("transform", `translate(${g} 0)`);
    host.classList.toggle("ended", end);
    const t = new Date(c.t0 + (g - c.L) / span * (c.t1 - c.t0));
    $(host, ".phl").textContent = end ? "heute" : fmt(t);
    $(host, ".tldate").textContent = end ? "Stand heute" : "Stand am " + fmt(t);
    const d0 = new Date(t); d0.setHours(0, 0, 0, 0);
    $(host, ".dayc").style.transform = `translateX(${c.L + (+d0 - c.t0) / (c.t1 - c.t0) * span}px)`;
    $(host, ".wm").textContent = end ? "heute" : fmt(t);
    const on = evs.filter((e) => e.classList.contains("on"));
    const nr = on.filter((e) => e.dataset.rate === "1" && e.dataset.fin !== "1").length, nf = on.filter((e) => e.dataset.fin === "1").length;
    $(host, ".tlsum").textContent = `${nr} Bewertung${nr === 1 ? "" : "en"} abgegeben · ${nf} von 7 festgelegt`;
    sl.value = String(Math.round(P * 1000));
  }
  const lab = () => (btn.textContent = atEnd() ? "↻ Nochmal abspielen" : "▶ Weiter");
  function stop() { playing = false; cancelAnimationFrame(raf); lab(); }
  function play() {
    if (atEnd()) set(0);
    playing = true; btn.textContent = "❚❚ Pause";
    const from = P, dur = DUR * (1 - from), s = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - s) / dur);
      set(from + (1 - from) * k);
      if (k < 1 && playing) raf = requestAnimationFrame(step); else if (k >= 1) stop();
    };
    raf = requestAnimationFrame(step);
  }
  btn.onclick = () => (playing ? stop() : play());
  sl.oninput = () => { stop(); set(+sl.value / 1000); lab(); };
  $$(host, ".ev[data-tip]").forEach((g) => hover(g, () => { const e = c.tips[+g.dataset.tip!]; return tip(e.role, `${evText(e)} · ${fmtT(e.t)}`, e.text); }));
  set(0);
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); play(); } }, { threshold: 0.3 });
    io.observe(host);
    life.add(() => io.disconnect());
  } else life.timeout(play, 350);
}

