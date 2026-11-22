/**
 * Type definitions for the REST API v1 (docs/api/rest-api.md). They mirror the canonical
 * Pydantic models in backend/app/models; this module exports no runtime values.
 *
 * Decimals are strings ("1250.00"); timestamps are ISO 8601 UTC strings; ids are opaque strings.
 */

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

/** A region on a PDF page or image; origin top-left, `unit` states the coordinate space. */
export interface BoundingBox {
  page_number: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  unit: 'pt' | 'px' | 'normalized';
}

export interface SourceLocation {
  kind: 'spreadsheet' | 'delimited_text' | 'pdf_text' | 'ocr' | 'gaeb_xml' | 'gaeb_90' | 'word';
  sheet_name?: string | null;
  sheet_index?: number | null;
  page_number?: number | null;
  table_index?: number | null;
  /** 1-based row/record in the source */
  row_number?: number | null;
  /** 1-based column in the source */
  column_number?: number | null;
  line_number?: number | null;
  /** computed A1 reference for spreadsheet cells */
  a1?: string | null;
  bbox?: BoundingBox | null;
}

export interface CellRef {
  table_id: string;
  row_id: string;
  column_id: string;
  source?: SourceLocation | null;
}

/** The model (IFC) attached to a bill: its quantities are compared with the bill's. */
export interface ModelInfo {
  filename: string;
  sha256: string;
  size_bytes: number;
  /** IFC schema, e.g. IFC4X3_ADD2 */
  schema_name: string;
  project: string | null;
  elements: number;
  /** elements without a link to a bill position (item number) */
  unlinked_elements: number;
  /** item numbers the model's elements name */
  linked_positions: number;
}

export interface DocumentSummary {
  document_id: string;
  original_filename: string;
  format:
    | 'xlsx'
    | 'csv'
    | 'gaeb_x81'
    | 'gaeb_x83'
    | 'gaeb_x84'
    | 'gaeb_x86'
    | 'gaeb_d81'
    | 'gaeb_d83'
    | 'gaeb_d84'
    | 'gaeb_d86'
    | 'pdf'
    | 'docx';
  uploaded_at: string;
  processing_status: 'stored' | 'processed' | 'needs_review' | 'failed';
  failure_reason: string | null;
  profile_id: string;
  /** the attached model (IFC); null when none is attached */
  model?: ModelInfo | null;
  size_bytes: number;
  sha256: string;
  dataset_id: string | null;
  table_count: number;
  row_count: number;
  last_run: { run_id: string; status: string; finished_at: string | null; issue_count: number } | null;
}

export interface ExtractionWarning {
  code: string;
  message: string;
  table_id?: string | null;
  source?: SourceLocation | null;
  count?: number | null;
  /** false for purely informational notes */
  needs_review?: boolean;
}

export interface Column {
  column_id: string;
  position: number;
  source_column_number: number;
  original_header: string | null;
  normalized_name: string;
  inferred_type: string;
  type_profile: { counts: Record<string, number>; non_empty: number; dominant_type: string; dominant_share: number };
  mapping: { field_id: string; method: string; matched_synonym: string | null; similarity: number | null } | null;
  mapped_semantic_field: string | null;
  header_currency: string | null;
  decimal_separator: '.' | ',' | null;
}

export interface TableSummary {
  table_id: string;
  name: string;
  source: SourceLocation;
  /** header rows top to bottom (empty when no header row was found) */
  header: { header_row_numbers: number[]; method: string; matched_fields: string[]; note: string | null };
  row_count: number;
  row_kind_counts: Record<string, number>;
  columns: Column[];
}

export interface DatasetSummary {
  dataset_id: string;
  document_id: string;
  revision: number;
  profile_id: string;
  profile_version: string;
  created_at: string;
  extraction: {
    adapter_id: string;
    adapter_version: string;
    quality: 'ok' | 'needs_review' | 'failed';
    warnings: ExtractionWarning[];
    details: Record<string, unknown>;
  };
  tables: TableSummary[];
  /** table id -> unmapped required fields */
  required_fields_missing: Record<string, string[]>;
}

export interface DocumentDetail {
  document: DocumentSummary;
  /** null when extraction failed */
  dataset: DatasetSummary | null;
}

export interface Cell {
  raw_value: string | null;
  parsed_value: object | null;
  normalized_value: object | null;
  data_type: string;
  parse_status: 'exact' | 'inferred' | 'ambiguous' | 'failed' | 'unavailable' | 'not_applicable' | 'marker';
  parse_note: string | null;
  formula: { expression: string; cached_result_available: boolean } | null;
  number_format: string | null;
  source: SourceLocation;
  /** OCR/PDF only; null for XLSX and CSV */
  extraction_confidence: number | null;
  /** set exactly when parse_status is 'marker': what a token like "Incl." in a number column means */
  marker?: string | null;
}

export interface Row {
  row_id: string;
  position: number;
  source_row_number: number;
  classification: {
    kind: string;
    rule: string;
    matched_text: string | null;
    section_level: number | null;
    /** item rows: whether totals add it; null when the bill does not say */
    counts_toward_totals: boolean | null;
    totals_rule: string | null;
    /** an item of an optional section: counted up to that section's subtotal, not above it */
    not_counted_above_section_id?: string | null;
  };
  /** enclosing section row ids, outermost first */
  section_path: string[];
  /** the innermost enclosing section row */
  section_row_id: string | null;
  /** subtotal rows whose scope is known */
  closes_section_id: string | null;
  /** a reviewer marked the row as not data */
  excluded: boolean;
  /** keyed by column_id */
  cells: Record<string, Cell>;
}

export interface WorkspaceSummary {
  dataset_id: string;
  document_id: string;
  revision: number;
  table_count: number;
  rows_processed: number;
  item_rows: number;
  columns_total: number;
  columns_mapped: number;
  required_fields_missing: string[];
  extraction_quality: string;
  extraction_warning_count: number;
  run: {
    run_id: string;
    status: string;
    review_status: 'in_progress' | 'finished';
    review_finished_at: string | null;
    planner: string;
    started_at: string;
    finished_at: string | null;
  } | null;
  /** effective evidence-class counts plus total and pending_review */
  counts: Record<string, number>;
}

export interface DetectorRunReport {
  detector_id: string;
  detector_version: string;
  /** `stopped`: the run's time limit stopped it; its findings so far are kept */
  status: 'completed' | 'skipped' | 'failed' | 'stopped';
  config: Record<string, unknown>;
  rationale: string | null;
  issues_found: number;
  issues_dropped: number;
  duration_ms: number;
  skipped_reasons: string[];
  /** set when a run limit stopped the detector early */
  limit_reached?: 'issues' | 'time' | null;
  error: string | null;
  notes: string[];
  coverage: Record<string, number>;
}

export interface ValidationRunSummary {
  run_id: string;
  dataset_id: string;
  dataset_revision: number;
  status: 'queued' | 'running' | 'completed' | 'completed_with_errors' | 'failed';
  review_status: 'in_progress' | 'finished';
  review_finished_at: string | null;
  planner: string;
  started_at: string;
  finished_at: string | null;
  issue_count: number;
  detectors: { completed: number; skipped: number; failed: number };
}

export interface ValidationRunDetail {
  run_id: string;
  document_id: string;
  dataset_id: string;
  dataset_revision: number;
  profile_id: string;
  profile_version: string | null;
  status: string;
  review_status: 'in_progress' | 'finished';
  review_finished_at: string | null;
  plan: {
    planner: string;
    planner_detail: string | null;
    steps: object[];
    skipped_checks: { detector_id: string; reasons: string[] }[];
    missing_information: string[];
    human_review_requirements: string[];
    notes: string[];
  };
  started_at: string;
  finished_at: string | null;
  detector_reports: DetectorRunReport[];
  issue_count: number;
  warnings: string[];
  /**
   * `by_finding_category` is keyed by finding category, `none` for findings without one (about
   * reading the file, or of a detector the backend's category tables do not know)
   */
  issue_counts: {
    total: number;
    by_evidence_class: Record<string, number>;
    by_severity: Record<string, number>;
    by_review_status: Record<string, number>;
    by_detector: Record<string, number>;
    by_finding_category: Record<string, number>;
  };
}

export interface Calculation {
  operation: 'product' | 'sum' | 'percentage' | 'difference' | 'comparison';
  /** may be capped */
  operands: { label: string; value: string; cell: CellRef | null }[];
  operands_truncated: boolean;
  /** full operand count */
  terms: number;
  exact_result: string;
  /** e.g. "2 decimal places, half up"; null = exact result used */
  rounding: string | null;
  rounded_result: string | null;
  reported: string | null;
  /** reported - expected */
  difference: string | null;
  allowed_difference: string | null;
}

export interface ValidationIssue {
  issue_id: string;
  fingerprint: string;
  evidence_digest: string | null;
  validation_run_id: string;
  /** the review version, sent back as `expected_version` */
  version: number;
  created_at: string;
  document_id: string;
  dataset_id: string;
  dataset_revision: number;
  table_id: string | null;
  row_id: string | null;
  /** highlighted cells */
  affected_cells: CellRef[];
  /** cells the finding was computed from */
  input_cells: CellRef[];
  detector_id: string;
  detector_version: string;
  rule_id: string;
  issue_category: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  /** as assigned by the detector */
  evidence_class: string;
  /** human confirmation overrides the detector's class */
  effective_evidence_class: string;
  /**
   * computed from detector, rule and the detector's own class, so a review never changes it;
   * null for findings about reading the file (and for those of a detector the backend's
   * category tables do not know)
   */
  finding_category: 'error' | 'omission' | 'inconsistency' | 'ambiguity' | 'risk' | 'change_order_opportunity' | null;
  title: string;
  explanation: string;
  observed_value: string | null;
  expected_value: string | null;
  evidence: {
    kind: string;
    label: string;
    detail: string;
    cells: CellRef[];
    data: Record<string, unknown>;
    calculation: Calculation | null;
  }[];
  /** the recommendation, shown under that heading */
  suggested_action: string | null;
  /**
   * Present only with explicit currency. Reference deviations compare unit prices and scale by
   * quantity and discount; discrepancies are reported minus recomputed values.
   */
  estimated_financial_impact: {
    amount: string;
    currency: string | null;
    basis: string;
    kind: 'discrepancy' | 'potential_double_count' | 'reference_deviation';
    reported: string | null;
    recomputed: string | null;
  } | null;
  /** OCR/PDF only */
  extraction_confidence: number | null;
  anomaly_score: {
    value: number;
    method: string;
    interpretation: string;
    calibrated: boolean;
    calibration_reference: string | null;
    threshold: number | null;
  } | null;
  review_status: string;
  /** review statuses a plain review decision may set from `review_status` (sorted; empty when no decision is possible) */
  allowed_review_actions: string[];
  reviewer_comment: string | null;
  reviewed_at: string | null;
}

export interface AuditEvent {
  event_id: string;
  occurred_at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  summary: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  context: Record<string, unknown>;
}

export interface IssueDetail {
  issue: ValidationIssue;
  history: AuditEvent[];
}

export interface CorrectedCell {
  table_id: string;
  row_id: string;
  column_id: string;
  previous_raw_value: string | null;
  corrected_raw_value: string | null;
  previous_data_type: string;
  corrected_data_type: string;
  previous_parse_status: string;
  corrected_parse_status: string;
}

/** `POST /datasets/{id}/corrections`: the revision after the request and the rows it changed. */
export interface CorrectionsResult {
  dataset_id: string;
  revision: number;
  parent_revision: number | null;
  /** cells whose text changed; 0 (and the revision unchanged) when nothing changed */
  changed: number;
  /** the changed rows of the new revision, in table order */
  rows: Row[];
}

export interface IssueCorrectionResult {
  issue: ValidationIssue;
  history: AuditEvent[];
  dataset: DatasetSummary;
  validation_run: ValidationRunDetail | null;
  corrected_cells: CorrectedCell[];
}

export interface DetectorDescriptor {
  spec: {
    detector_id: string;
    name: string;
    version: string;
    category: string;
    description: string;
    required_fields: string[];
    optional_fields: string[];
    supported_data_types: string[];
    applicability: string;
    evidence_classes: string[];
    issue_categories: string[];
    dependencies: string[];
    limitations: string[];
    license: string;
    references: string[];
    cost: string;
  };
  parameters_schema: Record<string, unknown>;
  default_config: Record<string, unknown>;
  /** parameters a client plan may set; the rest are controlled by the domain profile */
  plannable_parameters: string[];
  /**
   * with `?profile_id=`: the configuration a run on that profile uses when the plan sets nothing
   * (`default_config` with the profile's `detector_defaults` merged over it, validated); `null`
   * without the parameter
   */
  profile_config?: Record<string, unknown> | null;
}

export interface DetectorList {
  items: DetectorDescriptor[];
  /** the profile the descriptors' `profile_config` belongs to */
  profile_id?: string | null;
}

export interface ProfileSummary {
  profile_id: string;
  name: string;
  version: string;
  description: string;
  fields: { field_id: string; label: string; data_type: string; role: string; required: boolean }[];
  unit_count: number;
}

export interface Health {
  status: string;
  version: string;
  detector_count: number;
  profiles: string[];
  unavailable_detectors: { module: string; missing_package: string; message: string }[];
  ai_planner: { configured: boolean; note: string };
  /** the profile used when an upload names none */
  default_profile_id?: string;
  /** whether protected routes need `Authorization: Bearer <token>` */
  auth_required?: boolean;
  /** text recognition for scanned PDF pages */
  ocr?: { available: boolean; engine: string | null; languages: string; reason: string | null };
  /** the local language model; asked at most every 30 seconds */
  llm?: LlmStatus;
  /** whether a reviewer can send a bill to Claude for review (the server has an Anthropic key) */
  bill_review_available?: boolean;
}

export interface LlmStatus {
  provider: 'none' | 'ollama';
  /** the configured model, as the server names it */
  model: string | null;
  /** whether the server answered and has the model installed */
  ready: boolean;
  /** why the model is not ready, e.g. 'not configured' or 'server not reachable' */
  reason: string | null;
  server_version?: string | null;
  model_digest?: string | null;
}

/** Who the application acts for (GET /me). */
export interface Me {
  kind: 'user' | 'service' | 'local';
  name: string;
  email: string;
  role: 'admin' | 'reviewer' | 'viewer';
  user_id: string | null;
  auth_required: boolean;
  permissions: string[];
  /** the user's profile, for `kind` `user`; the others have none */
  account?: UserAccount | null;
}

/** A user account (GET /users). */
export interface UserAccount {
  user_id: string;
  /** the full name: first and last name */
  name: string;
  first_name: string;
  last_name: string;
  email: string;
  job_title: string;
  phone: string;
  role: 'admin' | 'reviewer' | 'viewer';
  active: boolean;
  created_at: string;
  /** the last four characters of the access token */
  token_hint: string | null;
  token_issued_at: string | null;
}

/** POST /users and POST /users/{id}/token: the token is shown once. */
export interface IssuedToken {
  user: UserAccount;
  token: string;
}

/** Bills open in the table view; supporting documents (drawings, reports, specs) open as the document itself. */
export type FileGroup = 'bill' | 'support';

/** A file of a project (bill or reference). */
export interface ProjectFile {
  document_id: string;
  role: 'bill' | 'reference';
  /** where a person put the file; null or absent: decided by the server */
  group?: FileGroup | null;
}

/** Values of one item that differ between the project's files. */
export interface ProjectCheck {
  item_code: string;
  field: string;
  documents: string[];
  values: string[];
  note: string;
}

/** The latest project-wide validation. */
export interface ProjectValidation {
  status: 'running' | 'completed' | 'failed';
  started_at: string;
  finished_at: string | null;
  /** run id by document id */
  runs: Record<string, string>;
  /** reason by document id */
  skipped: Record<string, string>;
  comparisons: ProjectCheck[];
  error: string | null;
}

export interface Project {
  project_id: string;
  name: string;
  description: string;
  created_at: string;
  status: 'in_progress' | 'finished';
  /** reviewer names */
  assignees: string[];
  /** the day of the bid decision, `YYYY-MM-DD` */
  decision_cutoff: string | null;
  files: ProjectFile[];
  demo_key: string | null;
  preparation: 'ready' | 'preparing' | 'failed';
  preparation_error: string | null;
  validation: ProjectValidation | null;
}

/** GET /projects/{id}: the project, its documents and live review counts per bill. */
export interface ProjectDetail {
  project: Project;
  documents: DocumentSummary[];
  review_counts: ReviewCounts;
  /** each file's group, by document id */
  groups?: Record<string, FileGroup>;
}

/** What is left to review in one bill of a project. */
export interface BillReviewCounts {
  to_review: number;
  high_priority: number;
  findings: number;
  /** every finding by priority (`critical`, `high`, `medium`, `low`, `info`); absent from older servers */
  by_severity?: Record<string, number>;
}

/** Review counts per bill, by document id. */
export type ReviewCounts = Record<string, BillReviewCounts>;

/**
 * Money behind a reminder. Amounts are exact decimal strings (never floats). `estimate` keeps
 * its range and basis: show it as an estimate, never as a confirmed loss. `reference` is a
 * comparison amount, never a loss.
 */
export interface RiskMoney {
  kind: 'exact' | 'estimate' | 'unknown';
  /** exact: the difference, never the item total */
  amount: string | null;
  currency: string | null;
  low: string | null;
  high: string | null;
  /** estimate: the quantity, the reference unit price and the positions it comes from */
  quantity?: string | null;
  reference_price?: string | null;
  comparable?: string | null;
  basis: string;
  share_of_total?: string | null;
  size_class?: string;
  reference: {
    amount: string;
    currency: string;
    basis: string;
    kind?: string;
    reported?: string | null;
    recomputed?: string | null;
    source_issue_id?: string;
    detector_id?: string;
  } | null;
}

export interface Risk {
  risk_id: string;
  /** the displayed position in its list */
  rank: number;
  /** the position in the default (priority) order */
  priority_rank: number | null;
  /** review priority, kept by every sort */
  tier: 'critical' | 'high' | 'medium' | 'low' | 'info';
  tier_rule?: string;
  tier_reason: string;
  state: 'risk' | 'cannot_tell';
  evidence_class: string;
  factors: {
    harm?: string;
    /** shown as "evidence certainty" (证据确定程度): a grouping, not a probability */
    certainty: 'confirmed' | 'suspected' | 'semantic' | 'unclear';
    challenge_priority?: string;
    independent_signals?: number;
    track_record?: { reviewed: number; confirmed: number; rejected: number } | null;
  };
  title: string;
  category: string;
  risk_type: string;
  risk_name?: string;
  direction?: string;
  methods?: string[];
  rules?: string[];
  /** text exactly as the bill states it (the evidence) */
  quotes: { position: string | null; source: string; text: string }[];
  why_risk_here: string;
  /** capped; `positions_total` counts them all */
  positions: { label: string; item_code: string | null; table_id: string; row_id: string; cells: CellRef[] }[];
  positions_total: number;
  /** what the bill says against the reminder */
  counter_evidence?: { position: string | null; source: string; text: string; link: string; detail: string }[];
  /** positions an evidence item names ("Rows summed", "Not counted"): evidence, not further problems */
  evidence_links?: { label: string; kind: string; positions: RiskPosition[]; positions_total: number }[];
  checked?: string[];
  missing_information?: string[];
  absence?: 'not_found_in_searched_scope' | 'in_document_not_provided' | 'stated_in_bill' | null;
  /** the findings the reminder was built from */
  source_issue_ids: string[];
  money: RiskMoney;
  question: string | null;
  suggested_action: string;
  /** why a sort placed it last (unknown money, other currency) */
  sort_note: string | null;
}

export interface OpenQuestion {
  kind: 'missing_document' | 'not_linked' | 'not_found' | 'other';
  topic: string;
  /** discovery: a model hypothesis to verify */
  source: 'checks' | 'discovery' | 'both';
  question: string;
  rules?: string[];
  risk_types?: string[];
  /** each distinct question one request answers */
  serves: string[];
  /** the reminders in `record` it stands for */
  reminder_ids: string[];
  /** labels (at most 10; see positions_total) */
  positions: string[];
  positions_total: number;
}

export interface RiskDisplayOrder {
  sort_by: 'priority' | 'price_impact' | 'confidence';
  sort_order: 'desc' | 'asc';
  policy_version: string;
  basis: string;
  ties: string;
  always_last: string;
  price_basis: string;
  incomparable_rule: string;
  open_questions: string;
}

/** A decision on a reminder without a finding (GET/PUT .../risk-reviews). */
export interface RiskReview {
  risk_id: string;
  status: 'open' | 'in_review' | 'approved' | 'rejected';
  comment: string;
  reviewed_at: string | null;
  /** the run the decision was made on */
  run_id?: string | null;
}

export interface RiskReport {
  format_version?: string;
  run_id: string;
  profile_id?: string;
  context?: {
    project_types?: string[];
    trades?: string[];
    positions: number;
    priced: boolean;
    currency: string | null;
    counted_total: string | null;
    documents_searched?: number;
  };
  /** includes `open_questions` and `open_questions_from_discovery` */
  counts: Record<string, number>;
  /** the main list */
  risks: Risk[];
  /** every other open reminder */
  record: Risk[];
  /** grouped, in the record's default order */
  open_questions: OpenQuestion[];
  /** how the doubts became reminders */
  funnel?: {
    raw_doubts: number;
    explained_automatically: number;
    below_size_threshold: number;
    open_after_search?: number;
    after_merging: number;
    main_list: number;
    kept_in_record: number;
    open_question_groups?: number;
    checks_missing_information?: string[];
  };
  /** one row per risk type: checked or not, and why */
  coverage?: {
    risk_type: string;
    name: string;
    category: string;
    state: string;
    reason: string;
    rules?: string[];
    checks?: { rule_id: string; state: string; reason: string; positions: string[]; positions_total: number }[];
  }[];
  /** status `outdated`: the stored run was made for other inputs and is not applied */
  discovery: {
    status: string;
    detail: string;
    discovery_run_id: string | null;
    kept: number;
    merged: number;
    processed: number;
    partly_read: number;
    not_processed: number;
  };
  display: RiskDisplayOrder;
  notes: string[];
}

/** A reminder as the bid risk report lists it (backend/app/risk/bid_report.py). */
export interface BidReminder {
  risk_id: string;
  tier: Risk['tier'];
  state: Risk['state'];
  title: string;
  risk_name: string;
  positions_total: number;
  /** the reminder's own money; never the position's line total */
  money: RiskMoney;
  question: string | null;
  suggested_action: string;
}

/** One row of the bid risk report: a position, its line total and the reminders on it. */
export interface BidPosition {
  rank: number;
  /** `largest`: listed for its line total alone, without a reminder */
  kind: 'reminders' | 'largest';
  document_id: string;
  document_name: string;
  run_id: string;
  label: string;
  item_code: string | null;
  table_id: string;
  row_id: string;
  short_text: string;
  quantity: string | null;
  unit: string | null;
  unit_price: string | null;
  line_total: string | null;
  currency: string | null;
  /** of its bill's counted total, 0 to 1 */
  share_of_total: string | null;
  reminders: BidReminder[];
}

/** A reminder no row holds: about many positions, none, or a row that is not a position. */
export interface BidOtherReminder {
  reason: 'many_positions' | 'no_position' | 'not_a_position';
  document_id: string;
  document_name: string;
  run_id: string;
  /** labels, capped; see `reminder.positions_total` */
  positions: string[];
  reminder: BidReminder;
}

export interface BidBill {
  document_id: string;
  document_name: string;
  run_id: string;
  run_status: string;
  positions: number;
  priced: boolean;
  currency: string | null;
  counted_total: string | null;
  reminders: number;
  /** reminders reviewers rejected, left out */
  rejected: number;
}

/** GET /projects/{id}/risk-report: the positions that drive price and risk, to hand over. */
export interface BidReport {
  project_id: string;
  project_name: string;
  generated_at: string;
  limit: number;
  positions: BidPosition[];
  /** rows with reminders before the cut to `limit` */
  positions_with_reminders: number;
  other_reminders: BidOtherReminder[];
  bills: BidBill[];
  /** files of the project with no part in the report, and why */
  skipped: { document_id: string; document_name: string; reason: string }[];
  /** share of the counted total that the largest line totals make up, 0 to 1 */
  largest_share: string | null;
  order_basis: string;
  notes: string[];
}

/** Findings of one run that concern the same mistake (backend/app/services/problems.py). */
export interface Problem {
  problem_id: string;
  issue_ids: string[];
  /** the finding shown first */
  primary_issue_id: string;
  /** why two findings belong together; `detail` says it in words */
  links: {
    kind: 'same_cell' | 'same_row' | 'carried_difference' | 'same_group';
    from_issue_id: string;
    to_issue_id: string;
    detail: string;
  }[];
  anomaly_type: 'price' | 'quantity' | 'unit' | 'semantic' | 'structural' | 'logical' | 'duplicate';
  /** exact decimal a check computed exactly (a difference or a double count); null otherwise */
  money_at_stake: string | null;
  /** the currency of `money_at_stake` */
  currency: string | null;
  /**
   * what would change if the primary finding's row were priced or measured like the positions it
   * was compared with: an estimate, never money at stake (its currency is the primary finding's
   * impact currency)
   */
  reference_deviation: string | null;
  title: string;
  finding_category: string | null;
  severity: string;
  /** exact decimal a rule recomputed */
  corrected_value: string | null;
  row_ids: string[];
}

export interface ProblemList {
  run_id: string;
  total: number;
  /** findings of the run, joined into the problems */
  findings: number;
  /** the most money at stake first */
  problems: Problem[];
}

export interface DiscoveryRunSummary {
  discovery_run_id: string;
  strategy: 'paths' | 'sample';
  status: 'queued' | 'running' | 'finished' | 'failed';
  /** completed, partial, over_budget, failed, not_processed */
  discovery_status: string | null;
  requested_at: string;
  finished_at: string | null;
  findings: number;
}

export interface DiscoveryRun extends DiscoveryRunSummary {
  run_id: string;
  inputs: Record<string, string>;
  seconds_total: number | null;
  seconds_model: number | null;
  error: string | null;
  timeout_note: string;
}

/** Parts of the types above that components take on their own. */
export type LastRun = NonNullable<DocumentSummary['last_run']>;
export type ValidationPlan = ValidationRunDetail['plan'];
export type EvidenceItem = ValidationIssue['evidence'][number];
export type FinancialImpact = NonNullable<ValidationIssue['estimated_financial_impact']>;
export type AnomalyScore = NonNullable<ValidationIssue['anomaly_score']>;
export type DetectorSpec = DetectorDescriptor['spec'];
export type RiskPosition = Risk['positions'][number];

/** A shared reviewer name (collaboration): a label anyone can choose, not a verified account. */
export interface Reviewer {
  handle: string;
  name: string;
}

/** GET /collaboration/session: this browser's reviewer, everyone who joined, and Desvio. */
export interface ReviewerSession {
  reviewer: Reviewer | null;
  reviewers: Reviewer[];
  bot?: { handle: string; name: string; connected: boolean };
}

export type TaskStatus = 'todo' | 'in_progress' | 'waiting' | 'done';
export type TaskType = 'check' | 'fix' | 'ask_client' | 'discussion';

/** The follow-up task of a finding: who does it, how far it is and what kind of work. */
export interface FindingTask {
  issue_id: string;
  assignee: string | null;
  assignee_name: string | null;
  status: TaskStatus;
  task_type: TaskType | null;
  /** YYYY-MM-DD, a calendar day */
  due_date?: string | null;
  updated_by: string;
  updated_at: string;
}

/** PUT /collaboration/issues/{id}/task: the whole task as it should be. */
export interface TaskInput {
  assignee: string | null;
  status: TaskStatus;
  task_type: TaskType | null;
  /** YYYY-MM-DD, or null to clear it */
  due_date?: string | null;
}

/** What Desvio attached to a reply: an email draft and one-click next steps. */
export interface AssistantAttachments {
  email_draft: { to: string; recipient: 'client' | 'bidder'; subject: string; body: string } | null;
  next_steps: {
    label: string;
    action?: 'assign' | 'set_status' | 'open_email' | 'none';
    assignee?: string;
    status?: TaskStatus;
  }[];
  /** in a project: the clarification the draft is listed as, to mark it sent */
  clarification?: {
    project_id: string;
    clarification_id: string;
    document_id: string;
    risk_id: string;
    tier: string;
    issue_id: string;
    title: string;
  } | null;
}

/** A comment on a finding, or an activity entry for a task change. */
export interface FindingComment {
  comment_id: string;
  issue_id: string;
  author: string;
  author_name: string;
  kind: 'comment' | 'activity';
  body: string;
  created_at: string;
  assistant?: AssistantAttachments | null;
}

/** GET /collaboration/issues/{id}/comments */
export interface CommentThread {
  items: FindingComment[];
  task: FindingTask | null;
  bot_working?: boolean;
}

/** A mention or assignment of the current reviewer, with its comment and finding. */
export interface MentionNotification {
  notification_id: string;
  recipient: string;
  comment_id: string;
  is_read: number;
  kind: FindingComment['kind'];
  author: string;
  author_name: string;
  body: string;
  created_at: string;
  issue_id: string;
  document_id: string;
  validation_run_id: string;
  issue_title: string;
}

/** GET /collaboration/notifications */
export interface NotificationList {
  items: MentionNotification[];
  unread_count: number;
}
