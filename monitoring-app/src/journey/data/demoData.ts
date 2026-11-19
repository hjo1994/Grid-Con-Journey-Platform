// Demo data for the evaluation journey, ported 1:1 from the approved mockup
// (data/mockups/workflow-bewertung-v3/src/data.js, window.GC). All names,
// values and comments are invented. Nothing here talks to the backend.

export type Role = "NP" | "RE" | "FI" | "BL";
export type EvType = "bewertet" | "geaendert" | "angefragt" | "festgelegt";
export type State = "offen" | "laeuft" | "abweichend" | "zweitpruefung" | "freigabe" | "fertig";
type SimKey = "kunde" | "tech" | "uw" | "mw";

export interface Ev {
  t: Date;
  role: Role;
  type: EvType;
  val?: number;
  from?: number;
  to?: Role;
  tag?: string | null;
  text?: string | null;
}

export interface Sub {
  key: string;
  crit: string;
  name: string;
  label: string;
  max: number;
  order: Role[];
  q: string;
  levels: string[];
  sim: SimKey[];
}

export interface SubState {
  key: string;
  events: Ev[];
  vals: Partial<Record<Role, number>>;
  comments: Ev[];
  pending: Ev | null;
  final: number | null;
  state: State;
  turn: Role | null;
  diverging: boolean;
  since: Date | null;
  consensus: number | null;
}

export interface Summary {
  done: number;
  total: number;
  turns: Partial<Record<Role, string[]>>;
  diverging: number;
  myTurn: number;
  lastT: Date | null;
  oldestWait: Date | null;
  phase: string;
  score: number;
  comments: number;
}

export interface Req {
  id: number;
  name: string;
  kunde: string;
  tech: string;
  mw: number;
  uw: string;
  progress: number | null;
  start: Date;
  subs: Record<string, SubState>;
  sum: Summary;
}

export interface Similar {
  req: Req;
  val: number | null;
  why: string[];
  w?: number;
  quote: string | null | undefined;
  by: Role | undefined;
}

export interface Point {
  text: string;
  roles: Role[];
}

export interface CommentSummary {
  tldr: string;
  agree: Point[];
  dispute: Point[];
  open: Point[];
}

export interface Guidance {
  sim: Similar[];
  dist: number[];
  suggest: number;
  because: string;
  level: string;
}

export const ROLES: Record<Role, { key: Role; name: string; cls: string }> = {
  NP: { key: "NP", name: "Netzplanung", cls: "np" },
  RE: { key: "RE", name: "Flächen & Recht", cls: "re" },
  FI: { key: "FI", name: "Finanzen", cls: "fi" },
  BL: { key: "BL", name: "Bewertungsleitung", cls: "bl" },
};
// The journey is shown as "Flächen & Recht" (the mockup sets GC.ME = 'RE').
export const ME: Role = "RE";
export const TODAY = new Date("2026-11-17T14:30:00");

// Sub-criteria with guideline levels. order = review order, BL decides at the end.
const SUB_DEFS: (Omit<Sub, "label"> & { label?: string })[] = [
  { key: "A1", crit: "A", name: "Flächensicherung", max: 2, order: ["RE", "NP", "FI"],
    q: "Sind Projektfläche und Fläche für das Kunden-UW gesichert?",
    levels: ["Kein Flächennachweis", "Absichtserklärung der Eigentümer", "Pacht- oder Kaufvertrag unterschrieben"],
    sim: ["kunde", "tech"] },
  { key: "A2", crit: "A", name: "Genehmigungsstand", max: 1, order: ["RE", "NP", "FI"],
    q: "Ist der Genehmigungsantrag für das Projekt gestellt?",
    levels: ["Noch kein Antrag", "Antrag eingereicht oder Vorbescheid positiv"],
    sim: ["tech", "uw"] },
  { key: "B12", crit: "B", name: "Technisches Konzept", label: "B1+B2", max: 1, order: ["NP", "RE", "FI"],
    q: "Sind Konzept für Projekt und Kunden-UW vollständig und plausibel?",
    levels: ["Konzept unvollständig", "SLD, Lageplan und Konzept plausibel"],
    sim: ["tech", "mw"] },
  { key: "B3", crit: "B", name: "Trassierung", max: 2, order: ["NP", "RE", "FI"],
    q: "Ist eine Kabeltrasse zum Netzverknüpfungspunkt geplant und sind die Wegerechte geklärt?",
    levels: ["Keine Trasse oder nur Grobkorridor", "Trasse geplant, Wegerechte in Klärung", "Trasse und alle Wegerechte gesichert"],
    sim: ["uw", "mw"] },
  { key: "C12", crit: "C", name: "Substanz und Bestellungen", label: "C1+C2", max: 2, order: ["FI", "RE", "NP"],
    q: "Gibt es verbindliche Bestellungen oder Rahmenverträge für Hauptkomponenten?",
    levels: ["Nur Angebote", "Rahmenvertrag im Entwurf oder LOI", "Verbindliche Bestellung der Hauptkomponenten"],
    sim: ["kunde", "tech"] },
  { key: "C3", crit: "C", name: "Bonität", max: 1, order: ["FI", "RE", "NP"],
    q: "Sind Bonität und Finanzierung des Antragstellers belegt?",
    levels: ["Bonität oder Finanzierung offen", "Aktuelle Bonitätsauskunft oder Finanzierungszusage"],
    sim: ["kunde"] },
  { key: "D1", crit: "D", name: "Hybridisierung", max: 2, order: ["NP", "FI", "RE"],
    q: "Wird das Projekt am selben Netzverknüpfungspunkt hybridisiert?",
    levels: ["Keine Hybridisierung", "Speicher oder zweite Technologie geplant", "Hybridisierung vertraglich gebunden"],
    sim: ["tech"] },
];
export const SUBS: Sub[] = SUB_DEFS.map((s) => ({ ...s, label: s.label || s.key }));
export const SUB: Record<string, Sub> = Object.fromEntries(SUBS.map((s) => [s.key, s]));

// Comment snippets per sub-criterion and value: [topic, text]
const POOL: Record<string, Record<number, [string, string][]>> = {
  A1: { 0: [["Flächennachweis fehlt", "Für das Kunden-UW liegt kein Flächennachweis vor."], ["Flächennachweis fehlt", "Nur Lageplan, keine Vereinbarung mit den Eigentümern."]],
        1: [["Absichtserklärung", "Absichtserklärung der Eigentümer liegt vor, Vertrag noch offen."], ["Absichtserklärung", "LOI für die Projektfläche, UW-Fläche noch in Verhandlung."]],
        2: [["Pachtvertrag", "Pachtvertrag für Projekt- und UW-Fläche unterschrieben."], ["Pachtvertrag", "Grundbuchauszug und Nutzungsvertrag vollständig."]] },
  A2: { 0: [["Kein Antrag", "Genehmigungsantrag noch nicht gestellt."], ["Kein Antrag", "Antrag ist laut Zeitplan erst für Q2 vorgesehen."]],
        1: [["Antrag eingereicht", "BImSchG-Antrag eingereicht, Eingangsbestätigung liegt bei."], ["Vorbescheid", "Bauvoranfrage positiv beschieden."]] },
  B12: { 0: [["SLD fehlt", "Single-Line-Diagramm fehlt, Konzept so nicht prüfbar."], ["Schutzkonzept", "Schutzkonzept für das Kunden-UW ist nicht beschrieben."]],
         1: [["Konzept plausibel", "SLD und Lageplan passen zusammen, Konzept plausibel."], ["Konzept plausibel", "Technisches Konzept vollständig, Schaltfelder abgestimmt."]] },
  B3: { 0: [["Wegerechte offen", "Keine Trasse festgelegt, Wegerechte nicht angefragt."], ["Grobkorridor", "Trasse nur als Grobkorridor, keine Eigentümergespräche."]],
        1: [["Wegerechte teilweise", "Trasse geplant, Gestattungsverträge für einen Teil der Flurstücke."], ["Trasse geplant", "Trasse technisch gesetzt, Wegerechte laufen noch."]],
        2: [["Wegerechte gesichert", "Trasse und alle Gestattungsverträge liegen vor."], ["Eigene Fläche", "Kurze Anbindung über eigenes Grundstück, keine Fremdflächen."]] },
  C12: { 0: [["Nur Angebote", "Keine Bestellungen, nur Herstellerangebote."], ["Nur Angebote", "Angebote älter als sechs Monate, nicht verbindlich."]],
         1: [["Rahmenvertrag Entwurf", "Rahmenvertrag im Entwurf, Preisblatt liegt vor."], ["LOI Hersteller", "LOI mit dem Hersteller, noch nicht bindend."]],
         2: [["Verbindliche Bestellung", "Verbindliche Bestellung der Hauptkomponenten liegt vor."], ["Anzahlung", "Anzahlung für die Trafos geleistet, Bestellung bestätigt."]] },
  C3: { 0: [["Bonität veraltet", "Bonitätsauskunft ist älter als zwölf Monate."], ["Finanzierung offen", "Finanzierung nicht nachgewiesen."]],
        1: [["Bonität belegt", "Aktuelle Bonitätsauskunft, Rating gut."], ["Finanzierungszusage", "Finanzierungszusage der Hausbank liegt vor."]] },
  D1: { 0: [["Einzelprojekt", "Reines Einzelprojekt, keine Kombination geplant."], ["Einzelprojekt", "Hybridisierung im Antrag nicht erwähnt."]],
        1: [["Speicher geplant", "Speicher als Option erwähnt, noch ohne Planung."], ["Speicher geplant", "Zweite Technologie in Prüfung, ohne Zeitplan."]],
        2: [["Hybrid gesichert", "PV und Speicher am selben Netzverknüpfungspunkt vertraglich gebunden."], ["Hybrid gesichert", "Gemeinsamer Anschlussvertrag für Wind und Speicher liegt vor."]] },
};

// Requests as in the app's overview (ticket, project, customer, technology, MW) + UW + progress
const BASE: [number, string, string, string, number, string, number | null][] = [
  [4913, "Projekt-G13", "Unternehmen-101 GmbH", "H2", 50, "UW Lauchstädt", 0.08],
  [4912, "Projekt-G12", "Unternehmen-100 GmbH", "WIND", 170, "UW Nord-3", 0.55],
  [4911, "Projekt-G11", "Unternehmen-105 GmbH", "PV", 150, "UW Ragow", 0.4],
  [4910, "Projekt-G10", "Unternehmen-104 GmbH", "BESS", 20, "UW Vierraden", 0.7],
  [4909, "Projekt-G09", "Unternehmen-103 GmbH", "DC", 70, "UW Nord-3", 1],
  [4908, "Projekt-G08", "Unternehmen-102 GmbH", "H2", 250, "UW Lauchstädt", 0.3],
  [4907, "Projekt-G07", "Unternehmen-101 GmbH", "WIND", 20, "UW Nord-3", 1],
  [4906, "Projekt-G06", "Unternehmen-100 GmbH", "PV", 350, "UW Ragow", 1],
  [4905, "Projekt-G05", "Unternehmen-105 GmbH", "BESS", 20, "UW Vierraden", 0.85],
  [4904, "Projekt-G04", "Unternehmen-104 GmbH", "DC", 250, "UW Nord-3", 1],
  [4903, "Projekt-G03", "Unternehmen-103 GmbH", "H2", 40, "UW Wolmirstedt", 0.6],
  [4902, "Projekt-G02", "Unternehmen-101 GmbH", "WIND", 300, "UW Nord-3", null],
  [4901, "Projekt-G01", "Unternehmen-101 GmbH", "WIND", 150, "UW Nord-3", 1],
  [4900, "Projekt-G00", "Unternehmen-100 GmbH", "BESS", 150, "UW Ragow", 1],
];

function rng(seed: number) {
  return function () {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
const D = (s: string) => new Date(s);
const addH = (d: Date, h: number) => new Date(d.getTime() + h * 3600e3);

// ---------- generated histories ----------
// Test data: every sub-criterion has a history of at least three ratings
// (bewertet / geaendert), often four. Where it ends:
//   fertig  all three reviewers rated, the Bewertungsleitung decided
//   bl      all three rated, waiting for the Bewertungsleitung
//   turn    waiting for one reviewer (often ME): either the two others rated
//           and one of them corrected, or all rated and a second review of
//           that reviewer was requested
type Mode = { k: "fertig" } | { k: "bl" } | { k: "turn"; who: Role };

function genSub(req: { start: Date }, sub: Sub, R: () => number, mode: Mode): Ev[] {
  const ev: Ev[] = [];
  const truth = Math.min(sub.max, Math.floor(R() * (sub.max + 1.6)));
  const off = (v: number) => (v === 0 ? 1 : v === sub.max ? v - 1 : v + (R() < 0.5 ? -1 : 1));
  let t = addH(req.start, R() * 48);
  const push = (e: Omit<Ev, "t">) => { t = addH(t, 4 + R() * 40); ev.push({ t, ...e }); };
  const rate = (role: Role, v: number) => {
    const c = R() < 0.85 ? POOL[sub.key][v][Math.floor(R() * POOL[sub.key][v].length)] : null;
    push({ role, type: "bewertet", val: v, tag: c && c[0], text: c && c[1] });
  };
  const change = (role: Role, from: number, to: number, why: string) => {
    const c = POOL[sub.key][to][0];
    push({ role, type: "geaendert", from, val: to, tag: c[0], text: why + " " + c[1] });
  };
  const ask = (role: Role, to: Role, text: string) => push({ role, type: "angefragt", to, tag: null, text });

  if (mode.k === "fertig" || mode.k === "bl") {
    // three ratings, one reviewer may deviate and correct after a query (4 ratings)
    const dev = R() < 0.6 ? sub.order[1 + Math.floor(R() * 2)] : null;
    sub.order.forEach((role) => rate(role, role === dev ? off(truth) : truth));
    if (dev && (mode.k === "fertig" || R() < 0.5)) {
      const v = ev.find((e) => e.role === dev)!.val!;
      ask(sub.order[0], dev, "Bitte noch einmal prüfen, die Unterlagen wurden ergänzt.");
      change(dev, v, truth, "Nach Rückfrage angepasst.");
    }
    if (mode.k === "fertig") push({ role: "BL", type: "festgelegt", val: truth, text: "Festgelegt, alle Prüfer einig." });
    return clampTimes(ev);
  }
  const who = mode.who, [a, b] = sub.order.filter((k) => k !== who);
  if (R() < 0.5) {
    // the two others rated, one corrected after the other's comment; `who` has not rated yet
    const va = off(truth);
    rate(a, va); rate(b, truth);
    change(a, va, truth, `Nach dem Hinweis von ${ROLES[b].name} angepasst.`);
    if (R() < 0.4) push({ role: b, type: "bewertet", val: truth, tag: null, text: "Nach den nachgereichten Unterlagen bestätigt." });
  } else {
    // all three rated, `who` deviates and is asked for a second review
    if (R() < 0.5) { const vb = off(truth); rate(b, vb); rate(a, truth); change(b, vb, truth, "Nach Rücksprache angepasst."); }
    else { rate(a, truth); rate(b, truth); }
    rate(who, off(truth));
    ask(a, who, "Sehe das anders, die Unterlagen wurden ergänzt. Bitte Zweitprüfung.");
  }
  return clampTimes(ev);
}

// Where each sub-criterion of a request ends; many wait for ME.
function modesOf(progress: number | null, R: () => number): Mode[] {
  if (progress === 1) return SUBS.map((): Mode => ({ k: "fertig" }));
  const p = progress ?? 0;
  const modes: Mode[] = SUBS.map((s) => {
    if (R() < p * 0.75) return { k: "fertig" };
    const r = R(), others = s.order.filter((k) => k !== ME);
    return r < 0.5 ? { k: "turn", who: ME } : r < 0.7 ? { k: "bl" } : { k: "turn", who: others[Math.floor(R() * others.length)] };
  });
  // an open request keeps at least one open sub-criterion, and most have one for ME
  if (!modes.some((m) => m.k !== "fertig")) modes[modes.length - 1] = { k: "turn", who: ME };
  if (!modes.some((m) => m.k === "turn" && m.who === ME) && R() < 0.75) {
    const i = modes.findIndex((m) => m.k !== "fertig");
    modes[i] = { k: "turn", who: ME };
  }
  return modes;
}
function clampTimes(ev: Ev[]) {
  // histories end at noon today at the latest
  const lim = addH(TODAY, -2);
  if (ev.length && ev[ev.length - 1].t > lim) {
    const shift = +ev[ev.length - 1].t - +lim;
    ev.forEach((e) => { e.t = new Date(+e.t - shift); });
  }
  return ev;
}

// ---------- hand-written focus case Projekt-G02 ----------
const G02: Record<string, Ev[]> = {
  A1: [
    { t: D("2026-10-28T09:10"), role: "RE", type: "bewertet", val: 2, tag: "Pachtvertrag", text: "Pachtvertrag für Projekt- und UW-Fläche unterschrieben, Grundbuchauszug liegt bei." },
    { t: D("2026-10-29T14:22"), role: "NP", type: "bewertet", val: 2, tag: "Pachtvertrag", text: "Passt, UW-Fläche deckt sich mit dem Lageplan." },
    { t: D("2026-10-30T10:05"), role: "FI", type: "bewertet", val: 2 },
    { t: D("2026-10-31T08:30"), role: "BL", type: "festgelegt", val: 2, text: "Festgelegt, alle Prüfer einig." }],
  A2: [
    { t: D("2026-10-28T09:40"), role: "RE", type: "bewertet", val: 1, tag: "Antrag eingereicht", text: "BImSchG-Antrag am 12.09. eingereicht, Eingangsbestätigung liegt vor." },
    { t: D("2026-10-29T14:30"), role: "NP", type: "bewertet", val: 1 },
    { t: D("2026-10-30T10:12"), role: "FI", type: "bewertet", val: 1 },
    { t: D("2026-10-31T08:32"), role: "BL", type: "festgelegt", val: 1, text: "Festgelegt, alle Prüfer einig." }],
  B12: [
    { t: D("2026-10-30T11:00"), role: "NP", type: "bewertet", val: 1, tag: "Konzept plausibel", text: "SLD und Lageplan passen zusammen, zwei Schaltfelder abgestimmt." },
    { t: D("2026-11-04T16:20"), role: "RE", type: "bewertet", val: 1 },
    { t: D("2026-11-13T09:45"), role: "FI", type: "bewertet", val: 1, tag: "Konzept plausibel", text: "Aus Sicht Finanzen keine Einwände." }],
  B3: [
    { t: D("2026-11-02T10:15"), role: "NP", type: "bewertet", val: 2, tag: "Trasse geplant", text: "Trasse ist technisch gesetzt, Wegerechte laut Kunde in Arbeit." },
    { t: D("2026-11-03T09:12"), role: "RE", type: "bewertet", val: 0, tag: "Wegerechte offen", text: "Wegerechte liegen nur als Entwurf vor, zwei Eigentümer fehlen noch. Deshalb 0." },
    { t: D("2026-11-03T11:40"), role: "NP", type: "geaendert", from: 2, val: 1, tag: "Wegerechte teilweise", text: "Die Trasse ist technisch gesetzt. Ich gehe auf 1, solange die Wegerechte laufen." },
    { t: D("2026-11-03T15:02"), role: "FI", type: "bewertet", val: 1, tag: "Trasse geplant", text: "Ich schließe mich der Netzplanung an." },
    { t: D("2026-11-12T08:50"), role: "NP", type: "angefragt", to: "RE", tag: "Wegerechte teilweise", text: "Der Kunde hat am 11.11. Gestattungsverträge für 70 % der Flurstücke nachgereicht. Bitte prüfe die 0 noch einmal." }],
  C12: [
    { t: D("2026-11-01T09:30"), role: "FI", type: "bewertet", val: 2, tag: "Verbindliche Bestellung", text: "Rahmenvertrag mit dem Turbinenhersteller liegt vor." },
    { t: D("2026-11-02T10:30"), role: "RE", type: "bewertet", val: 2, tag: "Verbindliche Bestellung", text: "Anlage A ist unterzeichnet, das reicht aus meiner Sicht für 2." },
    { t: D("2026-11-02T13:45"), role: "FI", type: "geaendert", from: 2, val: 1, tag: "Rahmenvertrag Entwurf", text: "Der Rahmenvertrag selbst ist noch Entwurf, Anlage A ist nur das Preisblatt. Ich habe auf 1 korrigiert." },
    { t: D("2026-11-05T15:10"), role: "NP", type: "bewertet", val: 1, tag: "Rahmenvertrag Entwurf", text: "Sehe es wie Finanzen, unterschrieben ist nur das Preisblatt." }],
  C3: [
    { t: D("2026-11-06T09:00"), role: "FI", type: "bewertet", val: 1, tag: "Bonität belegt", text: "Aktuelle Bonitätsauskunft vom 02.10., Rating gut." },
    { t: D("2026-11-14T11:25"), role: "RE", type: "bewertet", val: 1 },
    { t: D("2026-11-15T10:40"), role: "NP", type: "bewertet", val: 1, tag: "Bonität belegt", text: "Finanzierungszusage der Hausbank liegt ebenfalls bei." }],
  D1: [
    { t: D("2026-11-04T13:20"), role: "NP", type: "bewertet", val: 1, tag: "Speicher geplant", text: "Speicher am selben Netzverknüpfungspunkt ist im Antrag erwähnt, aber noch ohne Vertrag." },
    { t: D("2026-11-07T09:55"), role: "FI", type: "bewertet", val: 2, tag: "Hybrid gesichert", text: "Der gemeinsame Anschlussvertrag für Wind und Speicher liegt seit dem 06.11. vor." },
    { t: D("2026-11-10T16:05"), role: "NP", type: "geaendert", from: 1, val: 2, tag: "Hybrid gesichert", text: "Mit dem Anschlussvertrag ist die Hybridisierung gebunden. Ich gehe auf 2." }],
};

function median(a: number[]) { const s = a.slice().sort(); return s[Math.floor((s.length - 1) / 2)]; }

// State of a sub-criterion derived from its history
function derive(sub: Sub, events: Ev[]): SubState {
  const vals: Partial<Record<Role, number>> = {}, comments: Ev[] = [];
  let pending: Ev | null = null, final: number | null = null;
  events.forEach((e) => {
    if (e.type === "bewertet" || e.type === "geaendert") { vals[e.role] = e.val; if (pending && pending.to === e.role) pending = null; }
    if (e.type === "angefragt") pending = e;
    if (e.type === "festgelegt") final = e.val ?? null;
    if (e.text) comments.push(e);
  });
  const rated = sub.order.filter((r) => vals[r] !== undefined);
  const distinct = new Set(rated.map((r) => vals[r]));
  const diverging = distinct.size > 1;
  let state: State, turn: Role | null;
  if (final !== null) { state = "fertig"; turn = null; }
  else if (pending) { state = "zweitpruefung"; turn = (pending as Ev).to ?? null; }
  else if (rated.length < 3) { state = rated.length ? (diverging ? "abweichend" : "laeuft") : "offen"; turn = sub.order.find((r) => vals[r] === undefined) ?? null; }
  else if (diverging) { state = "abweichend"; turn = "BL"; }
  else { state = "freigabe"; turn = "BL"; }
  const last = events.length ? events[events.length - 1].t : null;
  const consensus = final !== null ? final : rated.length ? median(rated.map((r) => vals[r]!)) : null;
  return { key: sub.key, events, vals, comments, pending, final, state, turn, diverging, since: last, consensus };
}

// ---------- build ----------
export const REQUESTS: Req[] = BASE.map(([id, name, kunde, tech, mw, uw, progress], i) => {
  const start = progress === 1 ? addH(D("2026-10-06T08:00"), i * 20) : addH(D("2026-11-03T08:00"), ((i * 37) % 9) * 22);
  const req = { id, name, kunde, tech, mw, uw, progress, start, subs: {} as Record<string, SubState>, sum: null as unknown as Summary };
  const R = rng(id * 7 + 3), modes = modesOf(progress, R);
  SUBS.forEach((s, j) => {
    const events = id === 4902 ? G02[s.key] : genSub(req, s, R, modes[j]);
    req.subs[s.key] = derive(s, events);
    if (!req.subs[s.key].since) req.subs[s.key].since = id === 4902 ? D("2026-11-14T11:25") : req.start;
  });
  return req;
});
export const BY_ID: Record<number, Req> = Object.fromEntries(REQUESTS.map((r) => [r.id, r]));

// Maturity score after the formula of the evaluation Excel
function score(req: Req) {
  const v = (k: string) => req.subs[k].consensus ?? 0;
  return ((v("A1") + v("A2")) / 3 * 0.3 + (v("B12") + v("B3")) / 3 * 0.3 + (v("C12") + v("C3")) / 3 * 0.3 + v("D1") / 2 * 0.1);
}
function summaryOf(req: Req): Summary {
  const subs = SUBS.map((s) => req.subs[s.key]);
  const done = subs.filter((s) => s.state === "fertig").length;
  const turns: Partial<Record<Role, string[]>> = {};
  subs.forEach((s) => { if (s.turn) (turns[s.turn] = turns[s.turn] || []).push(s.key); });
  const diverging = subs.filter((s) => s.diverging && s.state !== "fertig").length;
  const myTurn = (turns[ME] || []).length;
  const lastT = subs.reduce<Date | null>((m, s) => (s.since && (!m || s.since > m) ? s.since : m), null);
  const oldestWait = subs.filter((s) => s.turn && s.since).reduce<Date | null>((m, s) => (!m || s.since! < m ? s.since : m), null);
  const phase = done === 7 ? "abgeschlossen" : subs.every((s) => s.state === "offen") ? "neu" : "in Bewertung";
  const ncom = subs.reduce((n, s) => n + s.comments.length, 0);
  return { done, total: 7, turns, diverging, myTurn, lastT, oldestWait, phase, score: score(req), comments: ncom };
}
REQUESTS.forEach((r) => { r.sum = summaryOf(r); });

// Comparable cases: same attributes per sub-criterion, only decided ratings
const REASON: Record<SimKey, string> = { kunde: "gleicher Kunde", tech: "gleiche Technologie", uw: "gleiches UW", mw: "ähnliche Leistung" };
function similarBase(reqId: number, subKey: string, n = 4): Similar[] {
  const req = BY_ID[reqId], sub = SUB[subKey];
  return REQUESTS.filter((o) => o.id !== reqId && o.subs[subKey].state === "fertig").map((o) => {
    const why: string[] = [];
    sub.sim.forEach((k) => {
      if (k === "mw" ? Math.abs(o.mw - req.mw) / Math.max(o.mw, req.mw) < 0.5 : o[k] === req[k]) why.push(REASON[k]);
    });
    (["tech", "uw", "kunde"] as const).forEach((k) => { if (!sub.sim.includes(k) && o[k] === req[k] && why.length < 2) why.push(REASON[k]); });
    const st = o.subs[subKey];
    const key = st.comments.filter((c) => c.type !== "festgelegt" && c.type !== "angefragt").pop();
    return { req: o, val: st.final, why, w: why.length + (sub.sim.includes("uw") && o.uw === req.uw ? 1 : 0), quote: key && key.text, by: key && key.role };
  }).filter((x) => x.why.length).sort((a, b) => b.w - a.w || b.req.id - a.req.id).slice(0, n);
}

const HANDMADE: Record<string, CommentSummary> = {
  "4902:B3": {
    tldr: "Alle sehen die Trasse als technisch geplant. Strittig ist nur, ob Wegerechte für 70 % der Flurstücke schon für 1 reichen.",
    agree: [{ text: "Trasse ist technisch gesetzt", roles: ["NP", "FI"] }, { text: "2 ist erst mit allen Gestattungsverträgen erreichbar", roles: ["NP", "RE"] }],
    dispute: [{ text: "Reichen teilweise gesicherte Wegerechte für 1? NP und FI: ja. RE: nein, solange zwei Eigentümer fehlen.", roles: ["NP", "RE", "FI"] }],
    open: [{ text: "Flächen & Recht prüft die am 11.11. nachgereichten Gestattungsverträge", roles: ["RE"] }],
  },
  "4902:C12": {
    tldr: "Unterschrieben ist nur Anlage A (Preisblatt), der Rahmenvertrag selbst ist Entwurf. Zwei von drei Prüfern geben deshalb 1.",
    agree: [{ text: "Anlage A ist unterzeichnet", roles: ["RE", "FI"] }],
    dispute: [{ text: "Zählt ein unterzeichnetes Preisblatt als verbindliche Bestellung? RE: ja (2). FI, NP: nein (1).", roles: ["RE", "FI", "NP"] }],
    open: [{ text: "Bewertungsleitung entscheidet zwischen 1 und 2", roles: ["BL"] }],
  },
};

// Comment summary (in the app an LLM; here prepared rule-based)
export function summarize(reqId: number, subKey: string): CommentSummary {
  const st = BY_ID[reqId].subs[subKey];
  const handmade = HANDMADE[reqId + ":" + subKey];
  if (handmade) return handmade;
  const themes: Record<string, { tag: string; roles: Set<Role>; vals: Set<number> }> = {};
  st.comments.forEach((c) => { if (!c.tag) return; (themes[c.tag] = themes[c.tag] || { tag: c.tag, roles: new Set(), vals: new Set() }); themes[c.tag].roles.add(c.role); if (c.val !== undefined) themes[c.tag].vals.add(c.val); });
  const list = Object.values(themes).map((t) => ({ tag: t.tag, roles: [...t.roles], vals: [...t.vals] }));
  const agree: Point[] = [], dispute: Point[] = [];
  if (st.diverging) list.forEach((t) => dispute.push({ text: t.tag + " (" + t.vals.join("/") + ")", roles: t.roles }));
  else list.forEach((t) => agree.push({ text: t.tag, roles: t.roles }));
  const open: Point[] = st.pending ? [{ text: "Zweitprüfung durch " + ROLES[st.pending.to!].name, roles: [st.pending.role] }] : [];
  let tldr: string;
  if (!st.comments.length) tldr = "Noch keine Kommentare.";
  else if (st.state === "fertig") tldr = "Einig bei " + st.final + ". " + (list[0] ? list[0].tag + " war ausschlaggebend." : "");
  else if (st.diverging) tldr = "Die Prüfer sehen das unterschiedlich: " + list.map((t) => t.tag).join(" vs. ") + ".";
  else tldr = "Bisher einig" + (list[0] ? ": " + list[0].tag + "." : ".");
  return { tldr, agree, dispute, open };
}

// Focus case: make the comparable cases for B3 a little more telling
const SIM_OVERRIDE: Record<string, { id: number; val: number; quote: string; by: Role }[]> = {
  "4902:B3": [
    { id: 4901, val: 1, quote: "Gestattungsverträge für rund zwei Drittel der Flurstücke, Rest in Verhandlung. Daher 1.", by: "RE" },
    { id: 4907, val: 1, quote: "Trasse geplant, ein Eigentümer verweigert noch. 1 mit Auflage.", by: "RE" },
    { id: 4909, val: 2, quote: "Alle Gestattungsverträge unterschrieben, Trasse genehmigt.", by: "RE" },
    { id: 4904, val: 0, quote: "Nur Grobkorridor, keine Eigentümergespräche.", by: "NP" }],
};
export function similar(reqId: number, subKey: string, n?: number): Similar[] {
  const o = SIM_OVERRIDE[reqId + ":" + subKey];
  if (!o) return similarBase(reqId, subKey, n);
  const req = BY_ID[reqId];
  return o.map((x) => {
    const r = BY_ID[x.id], why: string[] = [];
    if (r.uw === req.uw) why.push("gleiches UW");
    if (r.tech === req.tech) why.push("gleiche Technologie");
    if (Math.abs(r.mw - req.mw) / Math.max(r.mw, req.mw) < 0.5) why.push("ähnliche Leistung");
    return { req: r, val: x.val, why, quote: x.quote, by: x.by };
  }).slice(0, n || 4);
}
// The override cases must match the data set as well
Object.entries(SIM_OVERRIDE).forEach(([k, list]) => {
  const sk = k.split(":")[1], sub = SUB[sk];
  list.forEach((x) => {
    const r = BY_ID[x.id], old = r.subs[sk].events;
    const t = old[0] ? old[0].t : addH(r.start, 20);
    const ev: Ev[] = sub.order.map((role, i) => ({ t: addH(t, i * 26), role, type: "bewertet" as const, val: x.val, text: role === x.by ? x.quote : null, tag: role === x.by ? "Wegerechte" : null }));
    ev.push({ t: addH(t, 3 * 26 + 5), role: "BL", type: "festgelegt", val: x.val, text: "Festgelegt, alle Prüfer einig." });
    r.subs[sk] = derive(sub, ev);
  });
});
REQUESTS.forEach((r) => { r.sum = summaryOf(r); });

// Guidance: distribution of the comparable cases + suggestion
export function guidance(reqId: number, subKey: string): Guidance {
  const sub = SUB[subKey];
  // as in the mockup, guidance uses the plain search (the overrides are already in the data set)
  const sim = similarBase(reqId, subKey, 6);
  const dist = Array.from({ length: sub.max + 1 }, (_, v) => sim.filter((s) => s.val === v).length);
  // the most similar cases count more (rank weight), so ties are resolved
  const wd = dist.map((_, v) => sim.reduce((a, s, i) => a + (s.val === v ? 1 / (i + 1) : 0), 0));
  let suggest = wd.indexOf(Math.max(...wd));
  let because = !sim.length ? "Keine festgelegten Vergleichsfälle." : dist[suggest] > sim.length / 2 ? `${dist[suggest]} von ${sim.length} Vergleichsfällen landeten bei ${suggest}.` : `Die ähnlichsten Fälle (${sim.filter((s) => s.val === suggest).map((s) => s.req.name).join(", ")}) landeten bei ${suggest}.`;
  if (reqId === 4902 && subKey === "B3") { suggest = 1; because = "Bei teilweise gesicherten Wegerechten am UW Nord-3 wurde zweimal 1 vergeben, 0 nur ohne jeden Gestattungsvertrag."; }
  if (reqId === 4902 && subKey === "C12") { suggest = 1; because = "In vergleichbaren Fällen zählte nur der unterzeichnete Rahmenvertrag als Bestellung, ein Preisblatt allein ergab 1."; }
  return { sim, dist, suggest, because, level: sub.levels[suggest] };
}

// ---------- format helpers ----------
const pad = (n: number) => String(n).padStart(2, "0");
export const fmt = (d: Date | null | undefined) => (d ? pad(d.getDate()) + "." + pad(d.getMonth() + 1) + "." : "–");
export const fmtT = (d: Date | null | undefined) => (d ? fmt(d) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes()) : "–");
export const days = (d: Date | null | undefined) => (d ? Math.max(0, Math.round((+TODAY - +d) / 864e5)) : 0);
export const ago = (d: Date | null | undefined) => { const n = days(d); return n === 0 ? "heute" : n === 1 ? "seit gestern" : "seit " + n + " Tagen"; };
export const STATE: Record<State, { label: string; cls: string }> = {
  offen: { label: "Noch nicht begonnen", cls: "st-open" },
  laeuft: { label: "In Prüfung", cls: "st-run" },
  abweichend: { label: "Einschätzungen weichen ab", cls: "st-div" },
  zweitpruefung: { label: "Zweitprüfung angefragt", cls: "st-ask" },
  freigabe: { label: "Bereit zur Festlegung", cls: "st-ready" },
  fertig: { label: "Festgelegt", cls: "st-done" },
};
export const evText = (e: Ev) => ({
  bewertet: `bewertet mit ${e.val}`,
  geaendert: `ändert ${e.from} → ${e.val}`,
  angefragt: `fragt Zweitprüfung bei ${e.to && ROLES[e.to].name} an`,
  festgelegt: `legt ${e.val} fest`,
})[e.type];
