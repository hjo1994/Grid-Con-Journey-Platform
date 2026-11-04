import { useCallback, useEffect, useMemo, useState } from "react";

import { api, ApiError, type ListQuery } from "./api/client";
import type { AggregateResult, Customer, GridConnectionRequest, RequestPage, RequestStatus, SortField, User } from "./api/types";
import { DetailPanel } from "./components/DetailPanel";
import { EvaluationView } from "./components/EvaluationView";
import { HistoryView } from "./components/HistoryView";
import { Pager, RequestTable } from "./components/RequestTable";
import { ErrorNote } from "./components/small";
import { StatusWidget, TechWidget } from "./components/Widgets";
import { fmtShortDateTime } from "./domain/format";
import { hrefOf, useRoute } from "./domain/route";
import { groupByPhase, STOPPED_STATUS } from "./domain/status";
import { techShares } from "./domain/technology";

const PAGE_SIZE = 20;
const SEARCH_DELAY_MS = 300;

interface Reference {
  statuses: RequestStatus[];
  customers: Customer[];
  byStatus: AggregateResult;
  byTech: AggregateResult;
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Unerwarteter Fehler beim Laden der Daten.");
const isAbort = (err: unknown) => (err as Error)?.name === "AbortError";

// Newest of the data_as_of values the responses carry.
function latest(...values: (string | null | undefined)[]): string | null {
  return values.filter((v): v is string => !!v).sort().at(-1) ?? null;
}

const USER_KEY = "gridcon.userId";

function storedUserId(): string | null {
  try {
    return window.localStorage.getItem(USER_KEY);
  } catch {
    return null;
  }
}

// No authentication yet (see README): the user picks who they are. The choice
// is sent to the backend as X-User-ID when saving an evaluation.
function useCurrentUser() {
  const [users, setUsers] = useState<User[]>([]);
  const [userId, setUserId] = useState<string | null>(storedUserId);
  useEffect(() => {
    api.users().then(setUsers).catch(() => setUsers([]));
  }, []);
  const me = users.find((u) => u.id === userId) ?? users.find((u) => u.can_evaluate) ?? null;
  const choose = (id: string) => {
    setUserId(id);
    try {
      window.localStorage.setItem(USER_KEY, id);
    } catch {
      /* private mode: choice lasts for the session only */
    }
  };
  return { users, me, choose };
}

export default function App() {
  const route = useRoute();
  const { users, me, choose } = useCurrentUser();
  const [asOf, setAsOf] = useState<string | null>(null);

  return (
    <div className="app">
      <header className="bar">
        <span className="brand">
          GRID CON <i>Monitoring</i>
        </span>
        <nav>
          <a href="#/" className={route.page === "overview" ? "on" : undefined}>
            Übersicht
          </a>
          {route.page !== "overview" && (
            <a href={hrefOf(route)} className="on">
              {route.page === "history" ? "Verlauf" : "Bewertung"}
            </a>
          )}
        </nav>
        <span className="sync">
          {route.page === "overview" ? (
            <>
              Datenstand <b className={asOf ? "" : "unknown"}>●</b> {asOf ?? "unbekannt"}
            </>
          ) : (
            users.length > 0 && (
              <label className="me">
                angemeldet als{" "}
                <select value={me?.id ?? ""} onChange={(e) => choose(e.target.value)} aria-label="Nutzer:in wählen">
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.role_label} · {u.name ?? u.email}
                    </option>
                  ))}
                </select>
                {me && <span> · {me.can_evaluate ? "zur Bewertung berechtigt" : "nur lesend"}</span>}
              </label>
            )
          )}
        </span>
      </header>
      {route.page === "evaluation" ? (
        <main className="body">
          <EvaluationView key={route.id} id={route.id} me={me} />
        </main>
      ) : route.page === "history" ? (
        <main className="body">
          <HistoryView key={route.id} id={route.id} me={me} />
        </main>
      ) : (
        <Overview onAsOf={setAsOf} />
      )}
    </div>
  );
}

function Overview({ onAsOf }: { onAsOf: (asOf: string | null) => void }) {
  const [ref, setRef] = useState<Reference | null>(null);
  const [refError, setRefError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [query, setQuery] = useState<ListQuery>({ q: "", sort: "id_gronos_new", order: "desc", limit: PAGE_SIZE, offset: 0 });
  const [page, setPage] = useState<RequestPage | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<GridConnectionRequest | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    Promise.all([
      api.statuses(ctrl.signal),
      api.allCustomers(ctrl.signal),
      api.aggregate({ group_by: "request_status" }, ctrl.signal),
      api.aggregate({ group_by: "generation_technology", exclude_status: [STOPPED_STATUS], split_multi: true }, ctrl.signal),
    ])
      .then(([statuses, customers, byStatus, byTech]) => setRef({ statuses, customers, byStatus, byTech }))
      .catch((err) => !isAbort(err) && setRefError(errorText(err)));
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setQuery((q) => (q.q === search.trim() ? q : { ...q, q: search.trim(), offset: 0 })), SEARCH_DELAY_MS);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    api
      .requests(query, ctrl.signal)
      .then((p) => {
        setPage(p);
        setListError(null);
        setLoading(false);
        // Keep the selection while it is on the page, otherwise select the first row.
        setSelected((sel) => p.items.find((r) => r.id === sel?.id) ?? p.items[0] ?? null);
      })
      .catch((err) => {
        if (isAbort(err)) return;
        setListError(errorText(err));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [query]);

  const customers = useMemo(() => new Map((ref?.customers ?? []).map((c) => [c.id, c])), [ref]);
  const customerName = useCallback((id: string | null) => (id ? customers.get(id)?.customer_name ?? null : null), [customers]);
  const catalogue = ref?.statuses ?? [];
  const shares = useMemo(() => techShares(ref?.byTech.items ?? []), [ref]);
  const groups = useMemo(() => (ref ? groupByPhase(ref.byStatus.items, ref.statuses) : []), [ref]);

  const onSort = (key: SortField) =>
    setQuery((q) => ({
      ...q,
      sort: key,
      order: q.sort === key ? (q.order === "asc" ? "desc" : "asc") : key === "max_p" || key === "id_gronos_new" ? "desc" : "asc",
      offset: 0,
    }));

  const asOf = fmtShortDateTime(latest(page?.data_as_of, ref?.byStatus.data_as_of, ref?.byTech.data_as_of));
  useEffect(() => onAsOf(asOf), [asOf, onAsOf]);

  return (
      <main className="body">
        <div className="toolbar">
          <h2>Anfragen</h2>
          <input
            className="q"
            type="search"
            placeholder="Ticket-ID, Projekt oder Kunde suchen"
            aria-label="Suche"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="md">
          <div className="list">
            {listError ? (
              <ErrorNote message={listError} />
            ) : (
              <>
                <RequestTable
                  rows={page?.items ?? []}
                  customerName={customerName}
                  catalogue={catalogue}
                  techs={shares}
                  sort={query.sort}
                  order={query.order}
                  onSort={onSort}
                  selectedId={selected?.id ?? null}
                  onSelect={setSelected}
                  loading={loading}
                />
                {page && <Pager offset={query.offset} limit={query.limit} total={page.total} onPage={(offset) => setQuery((q) => ({ ...q, offset }))} />}
              </>
            )}
          </div>
          <DetailPanel request={selected} customer={selected?.customer_id ? customers.get(selected.customer_id) ?? null : null} catalogue={catalogue} />
        </div>

        {refError ? (
          <ErrorNote message={refError} />
        ) : (
          ref && (
            <div className="dgrid">
              <StatusWidget groups={groups} total={ref.byStatus.total} />
              <TechWidget shares={shares} activeCount={ref.byTech.total} />
            </div>
          )
        )}
      </main>
  );
}
