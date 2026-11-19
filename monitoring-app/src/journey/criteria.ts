// Criteria view of one request: timeline "Spur" -> sub-criterion cockpit ->
// evaluation cockpit, driven by clicks only, with a step bar to go back
// (mockup cockpit.js, journey block for ZONLY 'j').
import { BY_ID, ME, PASS_THRESHOLD, ROLES, SUB, SUBS } from "./data";
import { ctx, graph, head, lesetisch, P1 } from "./cockpit";
import { Sheet } from "./sheet";
import { initTimeline, timelineHtml } from "./timeline";
import { $, $$, esc, isSeen, Life, markSeen, RC, removePop } from "./ui";

export function mountCriteria(app: HTMLElement, id: number, onBack: () => void) {
  const life = new Life(), r = BY_ID[id], s = r.sum;

  // header right: actual points and passed / not passed instead of a percentage
  const pts = SUBS.reduce((n, sb) => n + (r.subs[sb.key].consensus ?? 0), 0), max = SUBS.reduce((n, sb) => n + sb.max, 0);
  const ok = pts >= PASS_THRESHOLD, fin = s.done === s.total;
  const score = `<div class="sc rsc"><span class="eyebrow">Bewertung der Anfrage</span><div class="rs"><b>${pts}<small>/ ${max} Punkte</small></b><span class="pf ${ok ? "ok" : "no"}">${fin ? "" : "VORLÄUFIG "}${ok ? "BESTANDEN" : "NICHT BESTANDEN"}</span></div>
    <div class="bar" style="--c:${ok ? "#5fd38d" : "#ff6b6b"}"><i></i><u style="left:${PASS_THRESHOLD / max * 100}%"></u></div><span class="rn">Schwelle ${PASS_THRESHOLD} Punkte${fin ? "" : ` · vorläufig, ${s.done} von ${s.total} festgelegt`}</span></div>`;
  const my = (s.turns[ME] || []).map((k) => SUB[k].label);
  const tl = timelineHtml(r);
  app.innerHTML = `<div class="rh"><div><div class="crumb">Anfragen / ${id} / Zeitstrahl</div><h1>${esc(r.name)}<small>${r.tech} · ${r.mw} MW · ${esc(r.kunde)} · ${esc(r.uw)}</small></h1></div>${score}</div>
    <p class="story">Ansicht als <b>Flächen &amp; Recht</b> · ${my.length ? "du bist bei <b>" + my.join(", ") + "</b> am Zug" : "du bist hier gerade nicht am Zug"}</p>
    <div class="jsteps"><button type="button" data-s="0" class="done"><b>◂</b>Anfragen<span>Übersicht</span></button><button type="button" data-s="1" class="on"><b>1</b>Kriterien<span>Zeitstrahl</span></button><button type="button" data-s="2"><b>2</b>Sub-Kriterium<span class="js2">Cockpit</span></button><button type="button" data-s="3"><b>3</b>Bewertung<span>Dokumente und Auswahl</span></button></div>
    <section class="zsec"><h2><b>1</b>Kriterien im Überblick</h2><p>Alle Sub-Kriterien der Anfrage im Zeitstrahl. Klick auf eine Zeile, um ihr Cockpit zu öffnen.</p>${tl.html}</section>
    <div class="cockpit"><div class="ck cka"></div></div>`;
  life.add(() => { app.innerHTML = ""; removePop(); });
  requestAnimationFrame(() => requestAnimationFrame(() => { $(app, ".rsc .bar i").style.width = (pts / max * 100) + "%"; }));

  const tsec = $(app, ".zsec"), tl2 = $(tsec, ".tl2"), cka = $(app, ".cka"), steps = $$(app, ".jsteps button");
  initTimeline(tl2, tl.geo, life, `tl:${id}`);

  let cur: string | null = null, gr: { stop(): void } | null = null, busy = false, isOpen = false;
  const sheet = new Sheet();
  life.add(() => sheet.close(false));
  const rate = new Life();
  life.add(() => { gr?.stop(); rate.stop(); });
  const step = (n: number) => steps.forEach((b) => { const k = +b.dataset.s!; b.classList.toggle("on", k === n); b.classList.toggle("done", k < n); });
  const stopG = () => gr?.stop();
  const stopR = () => rate.stop();

  function fill(key: string) {
    const cx = ctx(id, key);
    cur = key;
    $(app, ".js2").textContent = cx.sub.label + " " + cx.sub.name;
    cka.innerHTML = `<div class="cka-bar"><button type="button" class="ck-re ckback">◂ Zeitstrahl</button><div class="ck-tabs cksubs" style="margin-left:0">${SUBS.map((sb) => `<button type="button" data-k="${sb.key}" class="${sb.key === key ? "on" : ""}" title="${esc(sb.name)}">${sb.label}</button>`).join("")}</div></div>${head(cx)}<div class="ck-body"><div class="ck-in"></div></div>`;
    $(cka, ".ckback").addEventListener("click", back);
    $$(cka, ".cksubs button").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.k === cur) return;
      sheet.close(false); stopG(); stopR(); isOpen = false;
      fill(b.dataset.k!); cka.classList.add("in"); $(cka, ".ck-body").style.maxHeight = "none"; step(2); build();
    }));
  }
  function build() {
    stopG();
    const cx = ctx(id, cur!), inn = $(cka, ".ck-in"), turn = cx.st.turn, mine = turn === ME;
    const seenKey = `ck:${id}:${cur}`, instant = isSeen(seenKey);
    inn.innerHTML = P1.html(cx);
    const hk = P1.run(cka, life, instant);
    $(inn, ".ck-g").insertAdjacentHTML("afterend", `<div class="zhint"><i style="background:${turn ? RC[turn] : "var(--fg3)"}"></i>${mine ? "Du bist am Zug. Klick auf ZUG, um zu bewerten." : turn ? `${esc(ROLES[turn].name)} ist am Zug. Klick auf ZUG öffnet das Bewertungs-Cockpit.` : ""}</div><div class="zwrap"><div class="zbar"><span class="ck-cap">Bewertungs-Cockpit</span><button type="button" class="ck-re zclose" style="margin-left:auto">Schließen</button></div><div class="zrate"></div></div>`);
    $(inn, ".zclose").addEventListener("click", closeRate);
    const hint = $(inn, ".zhint");
    // comparable cases open the Seitenblatt
    $$(inn, ".simc").forEach((card) => {
      const go = () => sheet.open(cx, +card.dataset.sim!, card);
      card.addEventListener("click", go);
      card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });
    gr = graph($(inn, ".gh"), cx.st, cx.sub, {
      nowLabel: "ZUG", instant, onStart: () => markSeen(seenKey), onStep: hk.onStep, onNow: () => openRate(),
      onDone: () => { hk.onDone(); if (turn && !isOpen) hint.classList.add("on"); },
    });
  }
  function openRate() {
    const inn = $(cka, ".ck-in"), wrap = inn.querySelector<HTMLElement>(".zwrap"), box = $(inn, ".zrate");
    if (!wrap) return;
    stopR(); isOpen = true; step(3); $(inn, ".zhint").classList.remove("on");
    lesetisch(box, id, cur!, rate);
    wrap.classList.add("on"); wrap.style.maxHeight = wrap.scrollHeight + 40 + "px";
    life.timeout(() => { if (isOpen) wrap.style.maxHeight = "none"; }, 950);
    life.timeout(() => { const rr = wrap.getBoundingClientRect(); window.scrollBy({ top: rr.top - 150, behavior: "smooth" }); }, 250);
  }
  function closeRate() {
    const wrap = cka.querySelector<HTMLElement>(".zwrap");
    if (!wrap) return;
    isOpen = false; stopR(); step(2);
    wrap.style.maxHeight = wrap.scrollHeight + "px";
    requestAnimationFrame(() => requestAnimationFrame(() => { wrap.style.maxHeight = "0px"; wrap.classList.remove("on"); }));
    if (ctx(id, cur!).st.turn) $(cka, ".zhint").classList.add("on");
  }
  // the clicked timeline row lifts off and becomes the head of the cockpit
  function openA(key: string) {
    if (busy) return;
    busy = true;
    const row = $(tl2, `.row[data-sub="${key}"]`), cx = ctx(id, key);
    $$(tl2, ".row").forEach((rw) => rw.classList.toggle("pick", rw === row));
    tl2.classList.add("picking");
    const r0 = $(row, ".hit").getBoundingClientRect(), s0 = tsec.getBoundingClientRect();
    const gh = document.createElement("div");
    gh.className = "ckghost";
    gh.innerHTML = `<span>${cx.sub.label}</span>${esc(cx.sub.name)}`;
    Object.assign(gh.style, { top: r0.top + "px", left: r0.left + "px", width: r0.width + "px", height: r0.height + "px" });
    document.body.appendChild(gh);
    life.add(() => gh.remove());
    const top = Math.max(110, s0.top);
    life.timeout(() => { tsec.classList.add("leaving"); gh.classList.add("fly"); Object.assign(gh.style, { top: top + "px", left: s0.left + "px", width: s0.width + "px", height: "132px" }); }, 320);
    life.timeout(() => {
      tsec.style.display = "none"; fill(key); cka.classList.add("show"); step(2);
      if (s0.top < 110) window.scrollBy(0, cka.getBoundingClientRect().top - 110);
      requestAnimationFrame(() => requestAnimationFrame(() => {
        cka.classList.add("in"); gh.style.opacity = "0";
        const b = $(cka, ".ck-body");
        b.style.maxHeight = b.scrollHeight + "px";
        life.timeout(() => { b.style.maxHeight = "none"; gh.remove(); busy = false; }, 900);
        life.timeout(build, 420);
      }));
    }, 980);
  }
  function back() {
    sheet.close(false); stopG(); stopR(); isOpen = false;
    cka.classList.remove("show", "in"); cka.innerHTML = ""; cur = null; step(1);
    $(app, ".js2").textContent = "Cockpit";
    tsec.style.display = ""; tl2.classList.remove("picking"); $$(tl2, ".row").forEach((rw) => rw.classList.remove("pick"));
    requestAnimationFrame(() => requestAnimationFrame(() => tsec.classList.remove("leaving")));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  steps.forEach((b) => b.addEventListener("click", () => {
    if (!b.classList.contains("done")) return;
    const k = +b.dataset.s!;
    if (k === 0) { stopG(); stopR(); onBack(); }
    else if (k === 1) back();
    else if (k === 2) { closeRate(); window.scrollTo({ top: 0, behavior: "smooth" }); }
  }));
  $$(tl2, ".row").forEach((rw) => rw.addEventListener("click", () => openA(rw.dataset.sub!)));
  return () => life.stop();
}
