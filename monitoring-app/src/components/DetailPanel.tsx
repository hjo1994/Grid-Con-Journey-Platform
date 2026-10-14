import type { ReactNode } from "react";

import type { Customer, GridConnectionRequest, RequestStatus } from "../api/types";
import { fmtDateTime, fmtMW } from "../domain/format";
import { c4cTicketUrl, documentHref } from "../domain/links";
import { progressOf } from "../domain/status";
import { StatusPill } from "./small";

interface Props {
  request: GridConnectionRequest | null;
  customer: Customer | null;
  catalogue: RequestStatus[];
}

function Row({ label, value, mono }: { label: string; value: ReactNode | null; mono?: boolean }) {
  const missing = value === null || value === undefined || value === "";
  return (
    <>
      <dt>{label}</dt>
      <dd className={missing ? "na" : mono ? "mono" : undefined}>{missing ? "nicht gepflegt" : value}</dd>
    </>
  );
}

export function DetailPanel({ request: r, customer, catalogue }: Props) {
  if (!r) {
    return (
      <aside className="detail" aria-live="polite">
        <p className="dim">Anfrage in der Liste anklicken.</p>
      </aside>
    );
  }
  const { step, total } = progressOf(r.request_status, catalogue);
  const c4c = c4cTicketUrl(r.id_gronos_new);
  const doc = documentHref(r.document_url);

  return (
    <aside className="detail" aria-live="polite" aria-label="Details zur Anfrage">
      <div className="d-head">
        <div className="lbl mono">Ticket {r.id_gronos_new ?? "–"}</div>
        <h3>{r.id_gronos_old ?? "Ohne Projektname"}</h3>
        <div className="dim">{customer?.customer_name ?? "Kunde unbekannt"}</div>
        <div className="d-status">
          <StatusPill status={r.request_status} catalogue={catalogue} />
          <span className="num">{fmtMW(r.max_p)} MW</span>
        </div>
      </div>

      <div className="sec">
        <div className="lbl">Prozessfortschritt</div>
        <div className="steps" style={{ gridTemplateColumns: `repeat(${total || 1}, 1fr)` }} aria-hidden="true">
          {Array.from({ length: total }, (_, j) => (
            <i key={j} className={step === null ? "" : j + 1 < step ? "done" : j + 1 === step ? "cur" : ""} />
          ))}
        </div>
        <span className="dim small">
          {step !== null ? `Schritt ${step} von ${total}` : "Kein Prozessschritt, Anfrage liegt außerhalb des Prozesses"}
        </span>
      </div>

      <div className="sec">
        <div className="lbl">Dokumente und Links</div>
        <div className="links">
          {doc ? (
            <a className="lk" href={doc} target="_blank" rel="noreferrer">
              Antragsdokumente in ELO ↗
            </a>
          ) : (
            <span className={`lk ${r.document_url ? "" : "off"}`} title={r.document_url ? "Referenz, kein direkter Link" : undefined}>
              Antragsdokumente in ELO <small>{r.document_url ?? "kein Link"}</small>
            </span>
          )}
          {c4c ? (
            <a className="lk" href={c4c} target="_blank" rel="noreferrer">
              Ticket in C4C ↗
            </a>
          ) : (
            <span className="lk off">
              Ticket in C4C <small>nicht konfiguriert</small>
            </span>
          )}
        </div>
      </div>

      <div className="sec">
        <div className="lbl">Netzanschluss</div>
        <dl className="dl">
          <Row label="Technologie" value={r.generation_technology} />
          <Row label="Umspannwerk" value={r.substation_50hertz} mono />
          <Row label="Standort" value={r.substation_location} mono />
          <Row label="Schaltfelder" value={r.switch_count} />
        </dl>
      </div>

      <div className="sec">
        <div className="lbl">Ansprechpartner</div>
        <dl className="dl">
          <Row label="Name" value={customer?.customer_contact_person ?? null} />
          <Row
            label="E-Mail"
            value={
              customer?.customer_contact_person_email ? (
                <a href={`mailto:${customer.customer_contact_person_email}`}>{customer.customer_contact_person_email}</a>
              ) : null
            }
            mono
          />
        </dl>
      </div>

      {r.request_comment && (
        <div className="sec">
          <div className="lbl">Kommentar</div>
          <p className="comment">{r.request_comment}</p>
        </div>
      )}

      <div className="sec">
        <div className="lbl">Stand</div>
        <dl className="dl">
          <Row label="Zuletzt aktualisiert" value={fmtDateTime(r.timestamp)} />
        </dl>
      </div>
    </aside>
  );
}
