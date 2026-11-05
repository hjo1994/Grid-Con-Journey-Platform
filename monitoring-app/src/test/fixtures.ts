// Synthetic data in the backend's response shapes; no real data.
import type { AggregateResult, EvaluationCriterion, Customer, GridConnectionRequest, RequestPage, RequestStatus } from "../api/types";

const s = (name: string, order: number, phase: string | null): RequestStatus => ({ name, order, phase, in_process: phase !== null, configured: true });

export const STATUSES: RequestStatus[] = [
  s("Standortanfrage eingegangen", 1, "Eingang"),
  s("Netzanschlussantrag eingegangen", 2, "Eingang"),
  s("Netztechnische Prüfung positiv (intern)", 3, "Prüfung"),
  s("Reservierungsangebot angenommen", 4, "Reservierung & Umsetzung"),
  s("Offen", 5, null),
  s("Eingestellt", 6, null),
];

export const CUSTOMERS: Customer[] = [
  { id: "c1", customer_name: "Unternehmen-A", customer_contact_person: "Person-A", customer_contact_person_email: "a@example.invalid" },
  { id: "c2", customer_name: "Unternehmen-B", customer_contact_person: null, customer_contact_person_email: null },
  {
    id: "c3", customer_name: "Unternehmen-C", customer_contact_person: "Person-C", customer_contact_person_email: "c@example.invalid",
    company_id: "1000001", vat_number: "DE000000000",
  },
];

export const req = (over: Partial<GridConnectionRequest>): GridConnectionRequest => ({
  id: "r1",
  id_gronos_new: 1001,
  id_gronos_old: "Projekt-1",
  customer_id: "c1",
  business_transaction_id: "bt1",
  request_status: "Netzanschlussantrag eingegangen",
  generation_technology: "Batterie",
  max_p: 505,
  substation_50hertz: "Standort-1",
  substation_location: null,
  switch_count: 1,
  document_url: "Referenz-1",
  request_comment: null,
  timestamp: "2026-10-13T14:54:38Z",
  ...over,
});

export const PAGE: RequestPage = {
  items: [
    req({}),
    req({ id: "r2", id_gronos_new: 1002, id_gronos_old: "Projekt-2", customer_id: "c2", request_status: "Eingestellt", generation_technology: "Photovoltaik | Batterie", max_p: 120 }),
  ],
  total: 2,
  limit: 20,
  offset: 0,
  data_as_of: "2026-10-13T14:54:38Z",
};

// A request from the GRONOS API (codes instead of plain-text status)
export const GRONOS_PAGE: RequestPage = {
  ...PAGE,
  items: [
    req({
      id: "g1", id_gronos_new: 4902, id_gronos_old: "Projekt-G1", customer_id: "c3", request_status: "4",
      generation_technology: "BESS", max_p: 170, substation_50hertz: null, substation_location: "Teststraße 1, 12345 Testort",
      switch_count: null, document_url: "lageplan.pdf | vollmacht.pdf",
      gronos_object_id: "ABCDEF0123456789ABCDEF0123456789", next_actor: "2", project_phase: "Z01",
      dso_contacted: true, dso_response: "0", commissioning_date: "2027-01-01T00:00:00Z",
      latitude: 54.0594, longitude: 12.3322, source_updated_at: "2026-07-24T06:33:36Z",
    }),
  ],
  total: 1,
};

export const BY_STATUS: AggregateResult = {
  group_by: "request_status",
  split_multi: false,
  total: 4,
  items: [
    { key: "Netzanschlussantrag eingegangen", count: 2, sum_max_p: 700 },
    { key: "Eingestellt", count: 1, sum_max_p: 120 },
    { key: "Neuer Status", count: 1, sum_max_p: 50 },
  ],
  data_as_of: "2026-10-13T14:54:38Z",
};

export const BY_TECH: AggregateResult = {
  group_by: "generation_technology",
  split_multi: true,
  total: 3,
  items: [
    { key: "Batterie", count: 2, sum_max_p: 600 },
    { key: "Photovoltaik", count: 1, sum_max_p: 100 },
  ],
  data_as_of: "2026-10-13T14:54:38Z",
};

// Small evaluation framework in the shape of /evaluation-framework.
const chk = (id: string, check_type: "minimum" | "points", points = 0, alternative_group: string | null = null, graded = false) => ({
  id, description: null, check_type, points, graded, alternative_group, document_category: null,
});
const sub = (id: string, group: string, max: number, checks: ReturnType<typeof chk>[]) => ({
  id, name: id, scoring_group: group, scoring_group_name: group, max_score: max, question: null, checks,
});

export const FRAMEWORK: EvaluationCriterion[] = [
  { id: "F", name: "Formal", weight: 0, sub_criteria: [sub("F1", "F1", 0, [chk("F.1.1", "minimum")])] },
  { id: "B", name: "Technik", weight: 0.5, sub_criteria: [
    sub("B1", "B1+B2", 1, [chk("B1-01", "minimum")]),
    sub("B2", "B1+B2", 1, [chk("B2-06", "points", 1)]),
    sub("B3", "B3", 2, [chk("B3-01", "minimum"), chk("B3-03", "points", 1), chk("B3-04", "points", 2)]),
  ] },
  { id: "C", name: "Finanzen", weight: 0.5, sub_criteria: [
    sub("C1", "C1", 2, [chk("C1-01", "minimum", 0, "M"), chk("C1-02", "minimum", 0, "M"), chk("D1-01", "points", 2, null, true)]),
  ] },
];
