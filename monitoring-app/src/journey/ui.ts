// Small HTML helpers shared by the journey views (from the mockup's ui.js,
// shared.js and cockpit.js).
import { ROLES, ME, type Ev, type Role } from "./data";

export const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

// Role colours on the dark "Graphit" surface
export const RC: Record<Role, string> = { NP: "#5aa9ff", RE: "#ff9466", FI: "#5fd38d", BL: "#b494ff" };
export const LANES: Role[] = ["NP", "RE", "FI", "BL"];

export const av = (role: Role, cls = "", title?: string) =>
  `<span class="av ${ROLES[role].cls} ${cls}" title="${esc(title || ROLES[role].name)}">${role}</span>`;
export const rn = (k: Role) => ROLES[k].name + (k === ME ? " (du)" : "");
export const rk = (k: Role, x = "") => `<span class="rk ${x}" data-role="${k}" style="--c:${RC[k]}">${k}</span>`;
export const vb = (v: number | null | undefined, x = "") => `<span class="vb ${x}">${v ?? "–"}</span>`;
export const hm = (d: Date) => String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
export const act = (e: Ev) =>
  e.type === "bewertet" ? `bewertet mit ${e.val}`
    : e.type === "geaendert" ? `ändert von ${e.from} auf ${e.val}`
      : e.type === "angefragt" ? `bittet ${ROLES[e.to!].name} um erneute Prüfung`
        : `legt ${e.val} fest`;
export const qt = (e: Ev) => (e.text ? "„" + esc(e.text) + "“" : '<span style="color:var(--fg3)">ohne Kommentar</span>');

const NS = "http://www.w3.org/2000/svg";
export function svgEl(tag: string, at: Record<string, string | number> = {}, par?: Element): SVGElement & SVGGraphicsElement {
  const n = document.createElementNS(NS, tag) as SVGElement & SVGGraphicsElement;
  for (const k in at) n.setAttribute(k, String(at[k]));
  if (par) par.appendChild(n);
  return n;
}

// querySelector that the markup guarantees
export const $ = <T extends Element = HTMLElement>(root: ParentNode, sel: string) => root.querySelector(sel) as T;
export const $$ = <T extends Element = HTMLElement>(root: ParentNode, sel: string) => [...root.querySelectorAll(sel)] as T[];

// Popover on hover (one per page)
let popEl: HTMLDivElement | null = null;
function pop() {
  if (!popEl || !popEl.isConnected) {
    popEl = document.createElement("div");
    popEl.className = "pop";
    document.body.appendChild(popEl);
  }
  return popEl;
}
export function removePop() {
  popEl?.remove();
  popEl = null;
}
export function hover(el: Element, html: () => string) {
  el.addEventListener("mouseenter", () => {
    const p = pop();
    p.innerHTML = html();
    const b = el.getBoundingClientRect();
    p.style.left = Math.min(window.innerWidth - 316, b.left) + "px";
    const top = b.bottom + 8;
    p.style.top = (top + 300 > window.innerHeight ? b.top - p.offsetHeight - 8 : top) + "px";
    p.classList.add("on");
  });
  el.addEventListener("mouseleave", () => pop().classList.remove("on"));
}
export const tip = (role: Role, head: string, text?: string | null) =>
  `<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">${av(role)}<div><b>${ROLES[role].name}</b><div class="dim" style="font-size:11.5px">${head}</div></div></div>${text ? `<div style="line-height:1.45">${esc(text)}</div>` : ""}`;

// Collects timers, frames and observers of a view so it can be torn down.
export class Life {
  private stops: (() => void)[] = [];
  timeout(f: () => void, ms: number) {
    const t = window.setTimeout(f, ms);
    this.stops.push(() => clearTimeout(t));
    return t;
  }
  add(stop: () => void) {
    this.stops.push(stop);
  }
  stop() {
    this.stops.splice(0).forEach((f) => f());
  }
}
