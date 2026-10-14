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
