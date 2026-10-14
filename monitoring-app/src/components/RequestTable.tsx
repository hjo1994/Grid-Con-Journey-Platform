import type { GridConnectionRequest, RequestStatus, SortField, SortOrder } from "../api/types";
import { fmtMW } from "../domain/format";
import { slotOf, type TechShare } from "../domain/technology";
import { StatusPill, TechLabel } from "./small";

const COLUMNS: { key: SortField; label: string; right?: boolean }[] = [
  { key: "id_gronos_new", label: "Ticket", right: true },
  { key: "id_gronos_old", label: "Projekt" },
  { key: "customer_name", label: "Kunde" },
  { key: "generation_technology", label: "Technologie" },
  { key: "max_p", label: "MW", right: true },
  { key: "request_status", label: "Status" },
];

interface Props {
  rows: GridConnectionRequest[];
  customerName: (id: string | null) => string | null;
  catalogue: RequestStatus[];
  techs: TechShare[];
  sort: SortField;
  order: SortOrder;
  onSort: (key: SortField) => void;
  selectedId: string | null;
  onSelect: (row: GridConnectionRequest) => void;
  loading: boolean;
}

export function RequestTable({ rows, customerName, catalogue, techs, sort, order, onSort, selectedId, onSelect, loading }: Props) {
  return (
    <div className="tw" aria-busy={loading}>
      <table>
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                className={c.right ? "r" : undefined}
                aria-sort={sort === c.key ? (order === "asc" ? "ascending" : "descending") : "none"}
              >
                <button type="button" className="th-btn" onClick={() => onSort(c.key)}>
                  {c.label}
                  {sort === c.key && <span className="ar">{order === "asc" ? "▲" : "▼"}</span>}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              tabIndex={0}
              aria-selected={r.id === selectedId}
              className={r.id === selectedId ? "sel" : undefined}
              onClick={() => onSelect(r)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(r);
                }
              }}
            >
              <td className="r mono">{r.id_gronos_new ?? "–"}</td>
              <td>{r.id_gronos_old ?? <span className="dim">–</span>}</td>
              <td>{customerName(r.customer_id) ?? <span className="dim">–</span>}</td>
              <td>
                <TechLabel technology={r.generation_technology} slot={slotOf(r.generation_technology, techs)} />
              </td>
              <td className="r num">{fmtMW(r.max_p)}</td>
              <td>
                <StatusPill status={r.request_status} catalogue={catalogue} />
              </td>
            </tr>
          ))}
          {!rows.length && !loading && (
            <tr>
              <td colSpan={COLUMNS.length} className="empty">
                Keine Anfragen für diese Suche.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function Pager({ offset, limit, total, onPage }: { offset: number; limit: number; total: number; onPage: (offset: number) => void }) {
  const from = total ? offset + 1 : 0;
  const to = Math.min(total, offset + limit);
  return (
    <div className="pager">
      <span>
        {from}–{to} von {total}
      </span>
      <span className="btns">
        <button type="button" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}>
          Zurück
        </button>
        <button type="button" disabled={to >= total} onClick={() => onPage(offset + limit)}>
          Weiter
        </button>
      </span>
    </div>
  );
}
