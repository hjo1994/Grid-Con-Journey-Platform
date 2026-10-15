import type {
  AggregateResult,
  Customer,
  GridConnectionRequestWithCustomer,
  Meta,
  Page,
  RequestPage,
  RequestStatus,
  SortField,
  SortOrder,
} from "./types";
import { authHeaders } from "../shared/auth/accessToken";

const BASE = (import.meta.env.VITE_API_BASE || "/api/v1").replace(/\/$/, "");
const MAX_LIMIT = 500; // backend maximum

export class ApiError extends Error {
  constructor(
    public status: number | null,
    message: string,
  ) {
    super(message);
  }
}

// The backend's `detail` texts are not shown; the UI has its own message per status.
function messageFor(status: number | null): string {
  if (status === null) return "Das Backend ist nicht erreichbar.";
  if (status === 401) return "Du bist nicht angemeldet oder die Sitzung ist abgelaufen. Bitte melde dich neu an.";
  if (status === 403) return "Dir fehlt die Berechtigung für diese Daten.";
  if (status === 404) return "Die Anfrage wurde nicht gefunden.";
  if (status === 503) return "Die Datenbank ist gerade nicht verfügbar. Bitte gleich noch einmal versuchen.";
  return `Die Daten konnten nicht geladen werden (HTTP ${status}).`;
}

type Params = Record<string, string | number | boolean | readonly string[] | undefined>;

export function buildUrl(path: string, params: Params = {}): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => qs.append(key, v));
    else qs.append(key, String(value));
  }
  const query = qs.toString();
  return `${BASE}${path}${query ? `?${query}` : ""}`;
}

async function get<T>(path: string, params?: Params, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    const headers = { Accept: "application/json", ...(await authHeaders()) };
    res = await fetch(buildUrl(path, params), { headers, signal });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(null, messageFor(null));
  }
  if (!res.ok) throw new ApiError(res.status, messageFor(res.status));
  return (await res.json()) as T;
}

export interface ListQuery {
  q: string;
  sort: SortField;
  order: SortOrder;
  limit: number;
  offset: number;
}

export const api = {
  meta: (signal?: AbortSignal) => get<Meta>("/meta", undefined, signal),

  statuses: (signal?: AbortSignal) => get<RequestStatus[]>("/request-statuses", undefined, signal),

  requests: (query: ListQuery, signal?: AbortSignal) => get<RequestPage>("/grid-connection-requests", { ...query }, signal),

  request: (idGronosNew: number, signal?: AbortSignal) =>
    get<GridConnectionRequestWithCustomer>(`/grid-connection-requests/${idGronosNew}`, { expand: "customer" }, signal),

  aggregate: (params: { group_by: string; exclude_status?: string[]; split_multi?: boolean }, signal?: AbortSignal) =>
    get<AggregateResult>("/grid-connection-requests/aggregate", params, signal),

  // The request list carries only customer_id; names come from the customer
  // resource, loaded completely once (about 120 customers).
  async allCustomers(signal?: AbortSignal): Promise<Customer[]> {
    const items: Customer[] = [];
    for (;;) {
      const page = await get<Page<Customer>>("/grid-connection-customers", { limit: MAX_LIMIT, offset: items.length }, signal);
      items.push(...page.items);
      if (page.items.length === 0 || items.length >= page.total) return items;
    }
  },
};
