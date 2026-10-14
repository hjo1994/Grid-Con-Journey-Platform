// Response shapes of the backend (/api/v1), see backend/app/schemas.py.

export interface Customer {
  id: string;
  customer_name: string | null;
  customer_contact_person: string | null;
  customer_contact_person_email: string | null;
}

export interface GridConnectionRequest {
  id: string;
  id_gronos_new: number | null;
  id_gronos_old: string | null;
  customer_id: string | null;
  business_transaction_id: string | null;
  request_status: string | null;
  generation_technology: string | null;
  /** MW */
  max_p: number | null;
  substation_50hertz: string | null;
  substation_location: string | null;
  switch_count: number | null;
  document_url: string | null;
  request_comment: string | null;
  timestamp: string | null;
}

export interface GridConnectionRequestWithCustomer extends GridConnectionRequest {
  customer?: Customer | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface RequestPage extends Page<GridConnectionRequest> {
  data_as_of: string | null;
}

export interface AggregateItem {
  key: string | null;
  count: number;
  sum_max_p: number;
}

export interface AggregateResult {
  group_by: string;
  split_multi: boolean;
  total: number;
  items: AggregateItem[];
  data_as_of: string | null;
}

export interface RequestStatus {
  name: string;
  order: number | null;
  phase: string | null;
  in_process: boolean;
  configured: boolean;
}

export interface Meta {
  api_version: string;
  data_as_of: string | null;
}

export type SortField = "id_gronos_new" | "id_gronos_old" | "customer_name" | "generation_technology" | "max_p" | "request_status";
export type SortOrder = "asc" | "desc";
