/**
 * API payloads for tests, shaped like docs/api/rest-api.md. One small bill of quantities:
 * document doc_1 -> dataset ds_1 -> table tbl_1 ("LV"), validated by run_2 (latest) and run_1.
 */
import type {
  AuditEvent,
  Cell,
  CellRef,
  Column,
  DatasetSummary,
  DetectorList,
  DetectorRunReport,
  DocumentDetail,
  DocumentSummary,
  Health,
  Page,
  ProblemList,
  ProfileSummary,
  Risk,
  RiskMoney,
  RiskPosition,
  RiskReport,
  Row,
  SourceLocation,
  TableSummary,
  ValidationIssue,
  ValidationRunDetail,
  ValidationRunSummary,
} from '../services/apiTypes.ts';

const SHEET = 'LV';
const COLUMN_NUMBERS: Readonly<Record<string, number>> = { col_pos: 1, col_text: 2, col_qty: 3, col_price: 5, col_total: 6 };
const COLUMN_LETTERS: Readonly<Record<string, string>> = { col_pos: 'A', col_text: 'B', col_qty: 'C', col_price: 'E', col_total: 'F' };

/** Spreadsheet source location of a cell. */
export function source(columnId: string, rowNumber: number): SourceLocation {
  return {
    kind: 'spreadsheet',
    sheet_name: SHEET,
    sheet_index: 0,
    row_number: rowNumber,
    column_number: COLUMN_NUMBERS[columnId],
    a1: `${COLUMN_LETTERS[columnId]}${rowNumber}`,
  };
}

/** A canonical cell reference. */
export function cellRef(rowId: string, columnId: string, rowNumber: number): CellRef {
  return { table_id: 'tbl_1', row_id: rowId, column_id: columnId, source: source(columnId, rowNumber) };
}

function column(
  columnId: string,
  position: number,
  header: string,
  type: string,
  mapping: Column['mapping'],
  extra: Partial<Column> = {},
): Column {
  return {
    column_id: columnId,
    position,
    source_column_number: COLUMN_NUMBERS[columnId],
    original_header: header,
    normalized_name: header.toLowerCase().replace(/[^a-z0-9]+/g, '_'),
    inferred_type: type,
    type_profile: { counts: { [type]: 3 }, non_empty: 3, dominant_type: type, dominant_share: 1 },
    mapping,
    mapped_semantic_field: mapping?.field_id ?? null,
    header_currency: null,
    decimal_separator: type === 'number' ? '.' : null,
    ...extra,
  };
}

const exact = (fieldId: string, synonym: string): Column['mapping'] => ({ field_id: fieldId, method: 'header_exact', matched_synonym: synonym, similarity: null });

export const columns: Column[] = [
  column('col_pos', 0, 'Pos.', 'text', exact('item_number', 'Pos.')),
  column('col_text', 1, 'Kurztext', 'text', exact('description', 'Kurztext')),
  column('col_qty', 2, 'Menge', 'number', exact('quantity', 'Menge')),
  column('col_price', 3, 'Einheitspreis', 'number', exact('unit_price', 'Einheitspreis')),
  column('col_total', 4, 'Gesamtpreis', 'number', exact('line_total', 'Gesamtpreis'), { header_currency: 'EUR' }),
];

export const table: TableSummary = {
  table_id: 'tbl_1',
  name: 'LV',
  source: { kind: 'spreadsheet', sheet_name: SHEET, sheet_index: 0 },
  header: { header_row_numbers: [3], method: 'profile_synonyms', matched_fields: ['quantity', 'unit_price'], note: null },
  row_count: 3,
  row_kind_counts: { section: 1, item: 1, subtotal: 1 },
  columns,
};

export const dataset: DatasetSummary = {
  dataset_id: 'ds_1',
  document_id: 'doc_1',
  revision: 1,
  profile_id: 'boq',
  profile_version: '1.0.0',
  created_at: '2026-11-17T19:00:02Z',
  extraction: { adapter_id: 'xlsx.openpyxl', adapter_version: '1.0.0', quality: 'ok', warnings: [], details: {} },
  tables: [table],
  required_fields_missing: {},
};

export const documentSummary: DocumentSummary = {
  document_id: 'doc_1',
  original_filename: 'tender.xlsx',
  format: 'xlsx',
  uploaded_at: '2026-11-17T19:00:00Z',
  processing_status: 'processed',
  failure_reason: null,
  profile_id: 'boq',
  size_bytes: 48211,
  sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
  dataset_id: 'ds_1',
  table_count: 1,
  row_count: 3,
  last_run: { run_id: 'run_2', status: 'completed_with_errors', finished_at: '2026-11-17T19:05:01Z', issue_count: 2 },
};

export const documentDetail: DocumentDetail = { document: documentSummary, dataset };

type CellValue = string | null | [raw: string | null, options: { type?: string; status?: Cell['parse_status']; note?: string | null }];

function cell(
  columnId: string,
  rowNumber: number,
  raw: string | null,
  { type = 'text', status = 'exact', note = null }: { type?: string; status?: Cell['parse_status']; note?: string | null } = {},
): Cell {
  return {
    raw_value: raw,
    parsed_value: null,
    normalized_value: null,
    data_type: raw === null ? 'empty' : type,
    parse_status: raw === null ? 'not_applicable' : status,
    parse_note: note,
    formula: null,
    number_format: null,
    source: source(columnId, rowNumber),
    extraction_confidence: null,
  };
}

function row(
  rowId: string,
  rowNumber: number,
  kind: string,
  values: Record<string, CellValue>,
  extra: Partial<Row> = {},
): Row {
  const cells: Record<string, Cell> = {};
  for (const [columnId, value] of Object.entries(values)) {
    cells[columnId] = Array.isArray(value) ? cell(columnId, rowNumber, ...value) : cell(columnId, rowNumber, value);
  }
  return {
    row_id: rowId,
    position: rowNumber - 4,
    source_row_number: rowNumber,
    classification: {
      kind,
      rule: `pattern.${kind}`,
      matched_text: null,
      section_level: kind === 'section' ? 1 : null,
      counts_toward_totals: kind === 'item',
      totals_rule: null,
    },
    section_path: kind === 'section' ? [] : ['row_4'],
    section_row_id: kind === 'section' ? null : 'row_4',
    closes_section_id: kind === 'subtotal' ? 'row_4' : null,
    excluded: false,
    cells,
    ...extra,
  };
}

export const rows: Row[] = [
  row('row_4', 4, 'section', { col_pos: '01', col_text: 'Erdarbeiten', col_qty: null, col_price: null, col_total: null }),
  row('row_5', 5, 'item', {
    col_pos: '01.001',
    col_text: 'Oberboden abtragen',
    col_qty: ['12.5', { type: 'number' }],
    col_price: ['1,234', { type: 'text', status: 'ambiguous', note: '1,234 could be 1.234 or 1234; no value was chosen.' }],
    col_total: ['520.00', { type: 'number' }],
  }),
  row('row_6', 6, 'subtotal', { col_pos: null, col_text: 'Summe Erdarbeiten', col_qty: null, col_price: null, col_total: ['520.00', { type: 'number' }] }),
];

export const rowsPage: Page<Row> = { items: rows, total: 3, offset: 0, limit: 100 };

export const runSummaries: ValidationRunSummary[] = [
  {
    run_id: 'run_2',
    dataset_id: 'ds_1',
    dataset_revision: 1,
    status: 'completed_with_errors',
    review_status: 'in_progress',
    review_finished_at: null,
    planner: 'baseline',
    started_at: '2026-11-17T19:05:00Z',
    finished_at: '2026-11-17T19:05:01Z',
    issue_count: 2,
    detectors: { completed: 2, skipped: 1, failed: 1 },
  },
  {
    run_id: 'run_1',
    dataset_id: 'ds_1',
    dataset_revision: 1,
    status: 'completed',
    review_status: 'in_progress',
    review_finished_at: null,
    planner: 'baseline',
    started_at: '2026-11-17T19:01:00Z',
    finished_at: '2026-11-17T19:01:01Z',
    issue_count: 0,
    detectors: { completed: 2, skipped: 0, failed: 0 },
  },
];

function report(
  detectorId: string,
  status: DetectorRunReport['status'],
  extra: Partial<DetectorRunReport> = {},
): DetectorRunReport {
  return {
    detector_id: detectorId,
    detector_version: '1.0.0',
    status,
    config: {},
    rationale: null,
    issues_found: 0,
    issues_dropped: 0,
    duration_ms: 3.2,
    skipped_reasons: [],
    error: null,
    notes: [],
    coverage: {},
    ...extra,
  };
}

export const runDetail: ValidationRunDetail = {
  run_id: 'run_2',
  document_id: 'doc_1',
  dataset_id: 'ds_1',
  dataset_revision: 1,
  profile_id: 'boq',
  profile_version: '1.0.0',
  status: 'completed_with_errors',
  review_status: 'in_progress',
  review_finished_at: null,
  plan: {
    planner: 'baseline',
    planner_detail: null,
    steps: [
      { detector_id: 'deterministic.line_total', config: {}, rationale: null },
      { detector_id: 'statistical.unit_price_outlier', config: {}, rationale: null },
      { detector_id: 'domain.unit_plausibility', config: {}, rationale: null },
      { detector_id: 'deterministic.subtotal', config: {}, rationale: null },
    ],
    skipped_checks: [{ detector_id: 'semantic.description_unit', reasons: ['No semantic detector is installed.'] }],
    missing_information: [],
    human_review_requirements: [],
    notes: [],
  },
  started_at: '2026-11-17T19:05:00Z',
  finished_at: '2026-11-17T19:05:01Z',
  detector_reports: [
    report('deterministic.line_total', 'completed', {
      issues_found: 1,
      config: { tolerance: '0.01' },
      coverage: { rows_checked: 1, rows_skipped_missing_inputs: 0 },
    }),
    report('statistical.unit_price_outlier', 'completed', { issues_found: 1, coverage: { values_scored: 1 } }),
    report('domain.unit_plausibility', 'skipped', { skipped_reasons: ['Required field unit is not mapped.'] }),
    report('deterministic.subtotal', 'failed', { error: 'Section scope could not be resolved for row 6.' }),
  ],
  issue_count: 2,
  warnings: [],
  issue_counts: {
    total: 2,
    by_evidence_class: { confirmed_rule_violation: 1, suspected_anomaly: 1 },
    by_severity: { high: 1, medium: 1 },
    by_review_status: { pending_review: 2 },
    by_detector: { 'deterministic.line_total': 1, 'statistical.unit_price_outlier': 1 },
    by_finding_category: { error: 1, risk: 1 },
  },
};

export const lineTotalIssue: ValidationIssue = {
  issue_id: 'iss_1',
  fingerprint: 'fp_1',
  evidence_digest: 'ed_1',
  validation_run_id: 'run_2',
  document_id: 'doc_1',
  dataset_id: 'ds_1',
  dataset_revision: 1,
  table_id: 'tbl_1',
  row_id: 'row_5',
  affected_cells: [cellRef('row_5', 'col_total', 5)],
  input_cells: [cellRef('row_5', 'col_qty', 5), cellRef('row_5', 'col_price', 5)],
  detector_id: 'deterministic.line_total',
  detector_version: '1.0.0',
  rule_id: 'line_total',
  issue_category: 'arithmetic',
  severity: 'high',
  evidence_class: 'confirmed_rule_violation',
  effective_evidence_class: 'confirmed_rule_violation',
  finding_category: 'error',
  title: 'Line total does not equal quantity × unit price',
  explanation: 'The stated line total differs from quantity × unit price by more than the allowed rounding difference.',
  observed_value: '520.00',
  expected_value: '500.00',
  evidence: [
    {
      kind: 'calculation',
      label: 'Recomputed line total',
      detail: '12.5 × 40.00 = 500.00',
      cells: [cellRef('row_5', 'col_qty', 5), cellRef('row_5', 'col_price', 5)],
      data: {},
      calculation: {
        operation: 'product',
        operands: [
          { label: 'Quantity', value: '12.5', cell: cellRef('row_5', 'col_qty', 5) },
          { label: 'Unit price', value: '40.00', cell: cellRef('row_5', 'col_price', 5) },
        ],
        operands_truncated: false,
        terms: 2,
        exact_result: '500.000',
        rounding: '2 decimal places, half up',
        rounded_result: '500.00',
        reported: '520.00',
        difference: '20.00',
        allowed_difference: '0.01',
      },
    },
  ],
  suggested_action: 'Check the quantity, the unit price and the line total against the source.',
  estimated_financial_impact: {
    amount: '20.00',
    currency: 'EUR',
    basis: 'Stated line total minus recomputed line total',
    kind: 'discrepancy',
    reported: '520.00',
    recomputed: '500.00',
  },
  extraction_confidence: null,
  anomaly_score: null,
  review_status: 'pending_review',
  allowed_review_actions: ['confirmed_error', 'dismissed', 'false_positive', 'needs_more_information'],
  reviewer_comment: null,
  reviewed_at: null,
  version: 1,
  created_at: '2026-11-17T19:05:01Z',
};

// A finding of a signal check (a stand-in for statistical.peer_price), with the
// category the backend gives such findings: risk (plan section 5a puts unusual unit prices
// there). The interface shows the category the backend computed and never derives one.
export const outlierIssue: ValidationIssue = {
  ...lineTotalIssue,
  issue_id: 'iss_2',
  fingerprint: 'fp_2',
  evidence_digest: 'ed_2',
  affected_cells: [cellRef('row_5', 'col_price', 5)],
  input_cells: [],
  detector_id: 'statistical.unit_price_outlier',
  rule_id: 'robust_z',
  issue_category: 'statistical_outlier',
  severity: 'medium',
  evidence_class: 'suspected_anomaly',
  effective_evidence_class: 'suspected_anomaly',
  finding_category: 'risk',
  title: 'Unit price is unusually high for its unit',
  explanation: 'The unit price lies far outside the prices of comparable items.',
  observed_value: '40.00',
  expected_value: null,
  evidence: [],
  suggested_action: null,
  estimated_financial_impact: null,
  anomaly_score: {
    value: 4.31,
    method: 'robust_z_score',
    interpretation: 'Distance from the median in median absolute deviations; above 3.5 is unusual.',
    calibrated: false,
    calibration_reference: null,
    threshold: 3.5,
  },
};

export const issueHistory: AuditEvent[] = [
  {
    event_id: 'evt_1',
    occurred_at: '2026-11-17T19:05:01Z',
    actor: 'system',
    action: 'validation_run_completed',
    entity_type: 'validation_run',
    entity_id: 'run_2',
    summary: 'Validation run run_2 completed with 2 issues.',
    before: null,
    after: null,
    context: {},
  },
];

export const detectorCatalogue: DetectorList = {
  items: [
    {
      spec: {
        detector_id: 'deterministic.line_total',
        name: 'Line total arithmetic',
        version: '1.0.0',
        category: 'deterministic',
        description: 'Checks that each line total equals quantity × unit price within the rounding tolerance.',
        required_fields: ['quantity', 'unit_price', 'line_total'],
        optional_fields: [],
        supported_data_types: ['number'],
        applicability: 'Tables with quantity, unit price and line total mapped.',
        evidence_classes: ['confirmed_rule_violation'],
        issue_categories: ['arithmetic'],
        dependencies: [],
        limitations: ['Does not evaluate formulas; uses cached values.'],
        license: 'Apache-2.0',
        references: [],
        cost: 'low',
      },
      parameters_schema: { type: 'object', properties: { tolerance: { type: 'string' } } },
      default_config: { tolerance: '0.01', rounding: 'half_up' },
      plannable_parameters: [],
      profile_config: null,
    },
    {
      spec: {
        detector_id: 'statistical.unit_price_outlier',
        name: 'Unit price outliers',
        version: '1.0.0',
        category: 'statistical',
        description: 'Flags unit prices far from comparable items using a robust z-score.',
        required_fields: ['unit_price'],
        optional_fields: ['unit'],
        supported_data_types: ['number'],
        applicability: 'At least 8 priced items.',
        evidence_classes: ['suspected_anomaly'],
        issue_categories: ['statistical_outlier'],
        dependencies: [],
        limitations: ['Small tables give unstable scores.'],
        license: 'Apache-2.0',
        references: [],
        cost: 'low',
      },
      parameters_schema: { type: 'object', properties: { threshold: { type: 'number' } } },
      default_config: { threshold: 3.5, min_items: 8 },
      plannable_parameters: ['threshold'],
      profile_config: null,
    },
  ],
  profile_id: null,
};

export const profiles: { items: ProfileSummary[] } = {
  items: [
    {
      profile_id: 'boq',
      name: 'Bill of Quantities (construction)',
      version: '1.0.0',
      description: 'German and English bills of quantities.',
      fields: [
        { field_id: 'quantity', label: 'Quantity', data_type: 'number', role: 'quantity', required: true },
        { field_id: 'unit', label: 'Unit', data_type: 'text', role: 'unit', required: false },
      ],
      unit_count: 15,
    },
    {
      profile_id: 'generic',
      name: 'Generic table',
      version: '1.0.0',
      description: 'Any table.',
      fields: [],
      unit_count: 0,
    },
  ],
};

export const health: Health = {
  status: 'ok',
  version: '0.1.0',
  detector_count: 2,
  profiles: ['boq', 'generic'],
  unavailable_detectors: [
    {
      module: 'app.validation.machine_learning.isolation_forest',
      missing_package: 'scikit-learn',
      message: 'Install scikit-learn to enable this detector.',
    },
  ],
  ai_planner: { configured: false, note: 'Adaptive AI planning is not available in this version; every registered check runs.' },
};

// The two findings of run_2 joined into one problem (they concern the same row, row_5).
export const problemList: ProblemList = {
  run_id: 'run_2',
  total: 1,
  findings: 2,
  problems: [
    {
      problem_id: 'prb_iss_1',
      issue_ids: ['iss_1', 'iss_2'],
      primary_issue_id: 'iss_1',
      links: [{ kind: 'same_row', from_issue_id: 'iss_1', to_issue_id: 'iss_2', detail: 'Both concern the same position.' }],
      anomaly_type: 'logical',
      money_at_stake: '20.00',
      currency: 'EUR',
      reference_deviation: null,
      title: 'Line total does not equal quantity × unit price',
      finding_category: 'error',
      severity: 'high',
      corrected_value: '500.00',
      row_ids: ['row_5'],
    },
  ],
};

function riskPosition(label: string, rowId: string, columnIds: string[]): RiskPosition {
  return {
    label,
    item_code: label,
    table_id: 'tbl_1',
    row_id: rowId,
    cells: columnIds.map((columnId) => ({ table_id: 'tbl_1', row_id: rowId, column_id: columnId })),
  };
}

const NO_MONEY: RiskMoney = Object.freeze({
  kind: 'unknown',
  amount: null,
  currency: null,
  low: null,
  high: null,
  basis: 'No amount was computed.',
  size_class: 'medium',
  reference: null,
});

function risk(id: string, extra: Partial<Risk>): Risk {
  return {
    risk_id: id,
    rank: 1,
    priority_rank: 1,
    tier: 'medium',
    tier_reason: 'Open risk without a stronger rule.',
    title: 'A risk',
    risk_type: 'other',
    risk_name: 'Other risk',
    category: 'other',
    direction: 'cost_risk',
    state: 'risk',
    methods: ['invariant'],
    rules: ['R1'],
    positions: [riskPosition('01.001', 'row_5', ['col_total'])],
    positions_total: 1,
    quotes: [],
    evidence_links: [],
    counter_evidence: [],
    checked: [],
    missing_information: [],
    why_risk_here: 'Why this risk is here.',
    money: NO_MONEY,
    factors: { harm: 'money', certainty: 'confirmed' },
    question: null,
    suggested_action: '',
    source_issue_ids: [],
    ...extra,
  } as Risk; // a test risk: `extra` gives the fields a case needs
}

/**
 * The risk report of run_2: a risk with an exact amount behind the line total finding, a risk
 * with a comparison amount behind the unit price finding, a risk without a finding (a question
 * for the client) in the main list, and one reminder in the record.
 */
export const riskReport: RiskReport = {
  run_id: 'run_2',
  display: { sort_by: 'priority', sort_order: 'desc', policy_version: 'display-1', basis: '', ties: '', always_last: '', price_basis: '', incomparable_rule: '', open_questions: '' },
  counts: { reminders: 3, in_record: 1, high: 1, medium: 2, risk_types: 10, risk_types_checked: 4, open_questions: 1 },
  context: { positions: 1, priced: true, currency: 'EUR', counted_total: '520.00' },
  risks: [
    risk('risk_total', {
      rank: 1,
      priority_rank: 1,
      tier: 'high',
      title: 'Line total of 01.001 does not add up',
      risk_name: 'Arithmetic error',
      category: 'pricing',
      why_risk_here: 'The line total is 20.00 EUR above quantity times unit price.',
      money: { ...NO_MONEY, kind: 'exact', amount: '20.00', currency: 'EUR', basis: 'Stated minus recomputed line total', size_class: 'none' },
      suggested_action: 'Check the line total against the source.',
      source_issue_ids: ['iss_1'],
    }),
    risk('risk_price', {
      rank: 2,
      priority_rank: 2,
      title: 'Unit price of 01.001 far above comparable positions',
      risk_name: 'Unusual unit price',
      category: 'pricing',
      methods: ['peer_comparison'],
      positions: [riskPosition('01.001', 'row_5', ['col_price'])],
      factors: { harm: 'money', certainty: 'suspected' },
      money: {
        ...NO_MONEY,
        reference: {
          amount: '300.00',
          currency: 'EUR',
          basis: 'quantity × (unit price − median of comparable positions)',
          kind: 'reference_deviation',
          reported: '40.00',
          recomputed: '16.00',
        },
      },
      source_issue_ids: ['iss_2'],
    }),
    risk('risk_soil', {
      rank: 3,
      priority_rank: 3,
      title: 'Soil class of 01 not stated',
      risk_name: 'Unclear soil class',
      category: 'unclear_description',
      methods: ['vagueness'],
      positions: [riskPosition('01', 'row_4', ['col_text'])],
      factors: { harm: 'contract', certainty: 'semantic' },
      question: 'Which soil class applies to 01?',
      missing_information: ['a soil report'],
    }),
  ],
  record: [
    risk('risk_note', {
      rank: 4,
      priority_rank: 4,
      tier: 'low',
      title: 'Hint text without a position',
      category: 'other',
      positions: [],
      positions_total: 0,
    }),
  ],
  open_questions: [
    {
      kind: 'other',
      topic: 'soil',
      source: 'checks',
      question: 'Which soil class applies to 01?',
      serves: [],
      reminder_ids: [],
      positions: ['01'],
      positions_total: 1,
    },
  ],
  funnel: { raw_doubts: 6, explained_automatically: 1, below_size_threshold: 1, after_merging: 4, main_list: 3, kept_in_record: 1 },
  coverage: [],
  discovery: {
    status: 'not_requested',
    detail: 'No discovery run was requested.',
    discovery_run_id: null,
    kept: 0,
    merged: 0,
    processed: 0,
    partly_read: 0,
    not_processed: 0,
  },
  notes: ['Only this bill was searched.'],
};
