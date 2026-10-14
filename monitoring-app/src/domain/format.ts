const DE = "de-DE";

export const fmtInt = (n: number) => Math.round(n).toLocaleString(DE);

export const fmtMW = (n: number | null) => (n === null ? "–" : `${fmtInt(n)}`);

/** Backend timestamps are UTC ("…Z"); shown in the browser's local time. */
export function fmtDateTime(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(DE, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fmtShortDateTime(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const date = d.toLocaleDateString(DE, { day: "2-digit", month: "2-digit" });
  const time = d.toLocaleTimeString(DE, { hour: "2-digit", minute: "2-digit" });
  return `${date} ${time}`;
}
