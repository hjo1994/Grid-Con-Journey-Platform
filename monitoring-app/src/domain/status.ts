import type { AggregateItem, RequestStatus } from "../api/types";

// Status outside the process that ends a request. The widget "Leistung nach
// Technologie" excludes it, the status pill shows it in red.
export const STOPPED_STATUS = "Eingestellt";

export type Tone = "early" | "check" | "res" | "stop" | "neutral";
const PHASE_TONES: Tone[] = ["early", "check", "res"];

/** Process phases in catalogue order, e.g. Eingang, Prüfung, Reservierung & Umsetzung. */
export function phases(catalogue: RequestStatus[]): string[] {
  const seen: string[] = [];
  for (const s of sorted(catalogue)) if (s.in_process && s.phase && !seen.includes(s.phase)) seen.push(s.phase);
  return seen;
}

function sorted(catalogue: RequestStatus[]): RequestStatus[] {
  return [...catalogue].sort((a, b) => (a.order ?? Infinity) - (b.order ?? Infinity));
}

/** Colour of a status pill: by the position of its phase, red for "Eingestellt". */
export function toneOf(status: string | null, catalogue: RequestStatus[]): Tone {
  if (status === STOPPED_STATUS) return "stop";
  const entry = catalogue.find((s) => s.name === status);
  if (!entry?.in_process || !entry.phase) return "neutral";
  const i = phases(catalogue).indexOf(entry.phase);
  return PHASE_TONES[i % PHASE_TONES.length] ?? "neutral";
}

export interface Progress {
  /** 1-based step of the current status; null when the status is outside the process */
  step: number | null;
  total: number;
}

/** Process step of a status, derived from the in-process statuses of /request-statuses. */
export function progressOf(status: string | null, catalogue: RequestStatus[]): Progress {
  const steps = sorted(catalogue).filter((s) => s.in_process);
  const i = steps.findIndex((s) => s.name === status);
  return { step: i < 0 ? null : i + 1, total: steps.length };
}

export interface StatusRow {
  name: string;
  label: string;
  count: number;
  sumMaxP: number;
}

export interface StatusGroup {
  label: string;
  outside: boolean;
  count: number;
  rows: StatusRow[];
}

export const OUTSIDE_LABEL = "Außerhalb des Prozesses";
export const NO_STATUS_LABEL = "ohne Status";

/**
 * Widget "Status der Anfragen": one group per process phase, then everything
 * outside the process (configured or not, plus requests without status).
 * Configured statuses appear with 0 so that empty steps stay visible.
 */
export function groupByPhase(items: AggregateItem[], catalogue: RequestStatus[]): StatusGroup[] {
  const byKey = new Map(items.map((i) => [i.key, i]));
  const row = (name: string | null): StatusRow => ({
    name: name ?? "",
    label: name ?? NO_STATUS_LABEL,
    count: byKey.get(name)?.count ?? 0,
    sumMaxP: byKey.get(name)?.sum_max_p ?? 0,
  });
  const group = (label: string, outside: boolean, rows: StatusRow[]): StatusGroup => ({
    label,
    outside,
    rows,
    count: rows.reduce((n, r) => n + r.count, 0),
  });

  const cat = sorted(catalogue);
  const groups = phases(cat).map((phase) =>
    group(
      phase,
      false,
      cat.filter((s) => s.in_process && s.phase === phase).map((s) => row(s.name)),
    ),
  );
  const outsideNames: (string | null)[] = cat.filter((s) => !s.in_process).map((s) => s.name);
  for (const item of items) {
    const known = cat.some((s) => s.name === item.key && s.in_process);
    if (!known && !outsideNames.includes(item.key)) outsideNames.push(item.key);
  }
  if (outsideNames.length) groups.push(group(OUTSIDE_LABEL, true, outsideNames.map(row)));
  return groups;
}
