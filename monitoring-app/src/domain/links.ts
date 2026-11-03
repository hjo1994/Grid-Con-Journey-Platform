// C4C deep link, built in the app: the backend only knows the ticket ID.
const C4C_TEMPLATE = import.meta.env.VITE_C4C_TICKET_URL ?? "";

export function c4cTicketUrl(idGronosNew: number | null, template: string = C4C_TEMPLATE): string | null {
  if (!template || idGronosNew === null) return null;
  const id = encodeURIComponent(String(idGronosNew));
  return template.includes("{id}") ? template.replaceAll("{id}", id) : `${template.replace(/\/$/, "")}/${id}`;
}

/** DocumentURL holds an ELO reference; only real http(s) URLs become links. */
export function documentHref(documentUrl: string | null): string | null {
  return documentUrl && /^https?:\/\//i.test(documentUrl) ? documentUrl : null;
}

/** Map link for the plant coordinates (opened by the user, no request at load time). */
export function mapUrl(lat: number | null | undefined, lon: number | null | undefined): string | null {
  if (lat === null || lat === undefined || lon === null || lon === undefined) return null;
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=14/${lat}/${lon}`;
}

/** GRONOS delivers document file names only, " | "-separated. */
export function documentNames(documentUrl: string | null): string[] {
  if (!documentUrl || documentHref(documentUrl)) return [];
  return documentUrl.split(" | ").map((n) => n.trim()).filter(Boolean);
}
