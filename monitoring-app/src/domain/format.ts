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

/** Date only, e.g. commissioning date; the API sends UTC midnight-ish values. */
export function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(DE, { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function fmtYesNo(value: boolean | null | undefined): string | null {
  return value === null || value === undefined ? null : value ? "Ja" : "Nein";
}

/** 54.0593 / 12.3321 → "54,0593° N, 12,3321° O" */
export function fmtCoordinates(lat: number | null | undefined, lon: number | null | undefined): string | null {
  if (lat === null || lat === undefined || lon === null || lon === undefined) return null;
  const f = (n: number) => Math.abs(n).toLocaleString(DE, { minimumFractionDigits: 4, maximumFractionDigits: 4 });
  return `${f(lat)}° ${lat >= 0 ? "N" : "S"}, ${f(lon)}° ${lon >= 0 ? "O" : "W"}`;
}
