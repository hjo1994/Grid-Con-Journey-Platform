import type { AggregateItem } from "../api/types";

export const OTHER_LABEL = "Übrige";
export const TOP_N = 5;

export interface TechShare {
  label: string;
  /** colour slot 1..TOP_N, 0 for "Übrige" */
  slot: number;
  count: number;
  sumMaxP: number;
  share: number;
}

/**
 * Widget "Leistung nach Technologie": the TOP_N technologies by MW get their
 * own colour, the rest is summed up as "Übrige". With split_multi a request
 * with several technologies counts in each of them, so counts are mentions.
 */
export function techShares(items: AggregateItem[]): TechShare[] {
  const ranked = [...items].sort((a, b) => b.sum_max_p - a.sum_max_p);
  const total = ranked.reduce((s, i) => s + i.sum_max_p, 0);
  const share = (mw: number) => (total > 0 ? mw / total : 0);

  const top = ranked.filter((i) => i.key !== null).slice(0, TOP_N);
  const rest = ranked.filter((i) => !top.includes(i));
  const out: TechShare[] = top.map((i, n) => ({
    label: i.key as string,
    slot: n + 1,
    count: i.count,
    sumMaxP: i.sum_max_p,
    share: share(i.sum_max_p),
  }));
  if (rest.length) {
    const mw = rest.reduce((s, i) => s + i.sum_max_p, 0);
    out.push({ label: OTHER_LABEL, slot: 0, count: rest.reduce((s, i) => s + i.count, 0), sumMaxP: mw, share: share(mw) });
  }
  return out;
}

/** Colour slot of a (possibly multi-valued "A | B") technology in the list: that of its first value. */
export function slotOf(technology: string | null, shares: TechShare[]): number {
  const first = technology?.split(" | ")[0];
  return shares.find((s) => s.slot > 0 && s.label === first)?.slot ?? 0;
}
