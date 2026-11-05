// Response shapes of the backend (/api/v1), see backend/app/schemas.py.

export interface Customer {
  id: string;
  customer_name: string | null;
  customer_contact_person: string | null;
  customer_contact_person_email: string | null;
  /** GRONOS companyId; null for customers from the Excel import */
  company_id?: string | null;
  vat_number?: string | null;
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
  /** Time of the import into Silver (UTC) */
  timestamp: string | null;
  // --- GRONOS API only; null for requests from the Excel import
  gronos_object_id?: string | null;
  /** Codes until the GRONOS code lists are available */
  next_actor?: string | null;
  project_phase?: string | null;
  dso_contacted?: boolean | null;
  dso_response?: string | null;
  /** Earliest start date of the expansion stages (UTC) */
  commissioning_date?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  /** Last change in GRONOS (UTC) */
  source_updated_at?: string | null;
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

// Collaborative evaluation (K1/K4), see backend/app/api/evaluation.py.

export interface User {
  id: string;
  email: string;
  name: string | null;
  role: string;
  role_label: string;
  can_evaluate: boolean;
}

export interface EvaluationCheck {
  id: string;
  description: string | null;
  check_type: "minimum" | "points";
  points: number;
  graded: boolean;
  alternative_group: string | null;
  document_category: string | null;
}

export interface EvaluationSubCriterion {
  id: string;
  name: string;
  scoring_group: string;
  scoring_group_name: string;
  max_score: number;
  question: string | null;
  checks: EvaluationCheck[];
}

export interface EvaluationCriterion {
  id: string;
  name: string;
  weight: number;
  sub_criteria: EvaluationSubCriterion[];
}

export type Verdict = "fulfilled" | "not_fulfilled" | "open";

export interface EvaluationEntry {
  id: string;
  user_id: string;
  evaluation_check_id: string;
  verdict: Verdict;
  score: number | null;
  comment: string | null;
  version: number;
  timestamp: string;
  pending: boolean;
}

export interface EvaluationState {
  id_gronos_new: number;
  grid_connection_request_id: string;
  evaluators: User[];
  checks: EvaluationEntry[];
  last_change: string | null;
}

export interface HistoryEntry extends EvaluationEntry {
  action: "rated" | "changed" | "commented";
  previous_verdict: Verdict | null;
  previous_score: number | null;
  sub_criterion_id: string;
  scoring_group: string;
}

export interface EvaluationHistory {
  id_gronos_new: number;
  items: HistoryEntry[];
  total: number;
}

export interface EvaluationInputItem {
  evaluation_check_id: string;
  verdict: Verdict;
  score?: number | null;
  comment?: string | null;
}

/** "Meine Bewertungen": one request the user has evaluated with their current results. */
export interface UserEvaluationItem {
  id_gronos_new: number;
  id_gronos_old: string | null;
  generation_technology: string | null;
  max_p: number | null;
  request_status: string | null;
  checks: EvaluationEntry[];
  last_change: string;
  pending: boolean;
}

export interface UserEvaluations {
  user: User;
  items: UserEvaluationItem[];
  total: number;
}


// Reifegrad computed in the backend (backend/app/scoring.py).

/** Latest result of one check by one user, with the check's attributes. */
export interface CheckResult extends EvaluationEntry {
  sub_criterion_id: string;
  check_type: "minimum" | "points";
  points: number;
  graded: boolean;
  alternative_group: string | null;
}

export interface SubCriterionResult {
  sub_criterion_id: string;
  scoring_group: string;
  criterion_id: string;
  points: number | null;
  checks: CheckResult[];
}

export type GroupStatusOut = "complete" | "incomplete" | "min_failed" | "empty";

export interface GroupScoreOut {
  scoring_group: string;
  criterion_id: string;
  max_score: number;
  score: number | null;
  status: GroupStatusOut;
}

export interface ReviewerScore {
  user: User;
  percent: number | null;
  complete: boolean;
  deviates: boolean;
  last_change: string | null;
  sub_criteria: SubCriterionResult[];
  groups: GroupScoreOut[];
}

export interface CombinedScore {
  percent: number | null;
  method: "mean";
  done: number;
  total: number;
  complete: boolean;
  diverging_groups: string[];
}

/** GET /grid-connection-requests/{id}/evaluation-scores */
export interface RequestEvaluationScores {
  id_gronos_new: number;
  last_change: string | null;
  combined: CombinedScore;
  reviewers: ReviewerScore[];
}

export interface ReviewerSummary {
  user_id: string;
  name: string | null;
  role: string;
  role_label: string;
  short: string;
  percent: number | null;
  complete: boolean;
  deviates: boolean;
  last_change: string | null;
}

/** One item of GET /evaluation-scores (overview). */
export interface EvaluationScoreSummary {
  id_gronos_new: number;
  percent: number | null;
  done: number;
  total: number;
  complete: boolean;
  diverging_groups: string[];
  comment_count: number;
  last_change: string | null;
  reviewers: ReviewerSummary[];
}

export interface EvaluationScoreSummaries {
  items: EvaluationScoreSummary[];
  total: number;
}
