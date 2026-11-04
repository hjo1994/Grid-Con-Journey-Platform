import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { GridConnectionRequestWithCustomer } from "../api/types";
import { fmtMW } from "../domain/format";

export function useRequestHeader(id: number): GridConnectionRequestWithCustomer | null {
  const [request, setRequest] = useState<GridConnectionRequestWithCustomer | null>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    api.request(id, ctrl.signal).then(setRequest).catch(() => undefined);
    return () => ctrl.abort();
  }, [id]);
  return request;
}

export function RequestTitle({ header, subtitle }: { header: GridConnectionRequestWithCustomer | null; subtitle?: string }) {
  const facts = header
    ? [header.generation_technology, header.max_p !== null ? `${fmtMW(header.max_p)} MW` : null, header.customer?.customer_name].filter(Boolean)
    : [];
  return (
    <h2 className="ev-title">
      {header?.id_gronos_old ?? "Antrag"} <small>{subtitle ?? facts.join(" · ")}</small>
    </h2>
  );
}
