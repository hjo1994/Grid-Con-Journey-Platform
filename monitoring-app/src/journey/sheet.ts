// Seitenblatt: read-only cockpit of a comparable request for the same
// sub-criterion, slid in from the right over the user's own cockpit (which
// stays as it is underneath). Paged through the cases shown as cards.
import { ctx, graph, gboxHtml, head, P1, simCases, summaryHtml, voicesHtml, whysHtml, type Ctx } from "./cockpit";
import { $, $$, esc, isSeen, Life, markSeen } from "./ui";

export class Sheet {
  private root: HTMLDivElement | null = null;
  private life = new Life();
  private own: Ctx | null = null;
  private i = 0;
  private card: HTMLElement | null = null;
  private onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); this.close(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); this.page(-1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); this.page(1); }
  };

  open(own: Ctx, i: number, card: HTMLElement) {
    this.own = own;
    this.card = card;
    if (!this.root) {
      this.root = document.createElement("div");
      this.root.className = "sheet-wrap";
      this.root.innerHTML = `<div class="sheet-bg"></div><aside class="sheet" role="dialog" aria-modal="true" tabindex="-1"><div class="sh-top"></div><div class="sh-body"></div></aside>`;
      document.body.appendChild(this.root);
      $(this.root, ".sheet-bg").addEventListener("click", () => this.close());
      document.addEventListener("keydown", this.onKey);
      document.body.classList.add("sheet-lock");
      requestAnimationFrame(() => requestAnimationFrame(() => this.root?.classList.add("on")));
    }
    this.show(i);
  }

  close(restoreFocus = true) {
    if (!this.root) return;
    const root = this.root, card = this.card;
    this.life.stop();
    this.root = null;
    document.removeEventListener("keydown", this.onKey);
    document.body.classList.remove("sheet-lock");
    $$(document, ".simc.sel").forEach((c) => c.classList.remove("sel"));
    root.classList.remove("on");
    window.setTimeout(() => root.remove(), 500);
    if (restoreFocus) card?.focus();
  }

  private page(d: number) {
    if (!this.own) return;
    const n = simCases(this.own).length;
    if (n > 1) this.show((this.i + d + n) % n);
  }

  private show(i: number) {
    const own = this.own!, root = this.root!, cases = simCases(own), q = cases[i];
    this.i = i;
    this.life.stop();
    // mark the card of the case on display
    const cards = $$(document, ".simc");
    cards.forEach((c) => c.classList.toggle("sel", +c.dataset.sim! === i));
    this.card = cards.find((c) => +c.dataset.sim! === i) ?? this.card;

    const c = ctx(q.req.id, own.key), sheet = $(root, ".sheet");
    sheet.setAttribute("aria-label", `Vergleichsfall ${q.req.name}, ${c.sub.label} ${c.sub.name}`);
    $(root, ".sh-top").innerHTML = `<div class="sh-row"><span class="ck-cap">Vergleichsfall · nur lesen</span>
        <span class="sh-nav">${cases.length > 1 ? `<button type="button" class="sh-b" data-d="-1" aria-label="Vorheriger Vergleichsfall">◂</button><span class="sh-n">${i + 1} / ${cases.length}</span><button type="button" class="sh-b" data-d="1" aria-label="Nächster Vergleichsfall">▸</button>` : ""}<button type="button" class="sh-b sh-x">Schließen ✕</button></span></div>
      <div class="sh-row sh-id"><div class="sh-name"><h3>${esc(q.req.name)}</h3><span class="meta">Ticket ${q.req.id} · ${q.req.tech} · ${q.req.mw} MW · ${esc(q.req.uw)}</span>${whysHtml(q)}</div>
        <div class="sh-fix"><span>${c.sub.label} festgelegt</span><b>${c.st.final ?? "–"}</b></div></div>`;
    $$(root, ".sh-top [data-d]").forEach((b) => b.addEventListener("click", () => this.page(+b.dataset.d!)));
    $(root, ".sh-x").addEventListener("click", () => this.close());

    const body = $(root, ".sh-body");
    body.scrollTop = 0;
    body.innerHTML = head(c) + gboxHtml() + `<div class="ck-b sh-cols"><div class="sh-sec"><span class="ck-cap">Stimmen der Beteiligten</span><div class="sh-voices">${voicesHtml(c)}</div></div><div class="sh-sec sh-sum">${summaryHtml(c.sm)}</div></div>`;
    const key = `sheet:${q.req.id}:${own.key}`, instant = isSeen(key);
    const hk = P1.run(body, this.life, instant);
    const gr = graph($(body, ".gh"), c.st, c.sub, { instant, onStart: () => markSeen(key), onStep: hk.onStep, onDone: hk.onDone });
    this.life.add(() => gr.stop());
    sheet.focus({ preventScroll: true });
  }
}
