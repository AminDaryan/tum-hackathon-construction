/**
 * Display vocabulary for the backend's enumerations (backend/app/models). Pure data: labels,
 * descriptions, ordering and status tones. Icons and colours live in the components.
 *
 * Unknown values (for example a category added by a new detector) fall back to a humanized
 * label, so the UI never hides data it does not recognise.
 *
 * The labels and descriptions are English marked with `msg`; whoever shows one translates it
 * with `t` (labelFor and statusMeta already do).
 */
import { msg, t } from '../i18n/messages.ts';

/** "needs_more_information" -> "Needs more information". */
export function humanize(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const text = String(value).replace(/[_.]+/g, ' ').trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Looks a value up in a label map and translates it, falling back to {@link humanize}. */
export function labelFor(labels: Readonly<Record<string, string>>, value: string | null | undefined): string {
  return value && labels[value] ? t(labels[value]) : humanize(value);
}

export const EVIDENCE_CLASS_LABELS = Object.freeze({
  confirmed_rule_violation: msg('Rule violation'),
  suspected_anomaly: msg('Suspected anomaly'),
  semantic_warning: msg('Semantic warning'),
  extraction_uncertainty: msg('Extraction uncertainty'),
  needs_external_context: msg('Needs external context'),
  human_confirmed_error: msg('Human-confirmed'),
});

export const EVIDENCE_CLASS_DESCRIPTIONS: Readonly<Record<string, string>> = Object.freeze({
  confirmed_rule_violation: msg('A deterministic rule failed on verified input data.'),
  suspected_anomaly: msg('A statistical signal: an unusual observation, not a proven error.'),
  semantic_warning: msg('A possible inconsistency found through text or semantic analysis.'),
  extraction_uncertainty: msg('The original document could not be interpreted reliably.'),
  needs_external_context: msg('Cannot be resolved from this document alone.'),
  human_confirmed_error: msg('A reviewer explicitly confirmed this finding.'),
});

/**
 * Finding categories (backend/app/models/finding_category.py): what a finding means for the
 * person who checks the bill. In the order of the risk report; findings about reading the file
 * have no category (`finding_category: null`) and come last, under {@link NO_FINDING_CATEGORY}.
 */
export const FINDING_CATEGORY_ORDER = Object.freeze([
  'error',
  'inconsistency',
  'omission',
  'ambiguity',
  'risk',
  'change_order_opportunity',
]);

/** How the issue filter and the run's counts name the findings without a category. */
export const NO_FINDING_CATEGORY = 'none';

export const FINDING_CATEGORY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  error: msg('Error'),
  omission: msg('Omission'),
  inconsistency: msg('Inconsistency'),
  ambiguity: msg('Ambiguity'),
  risk: msg('Risk'),
  change_order_opportunity: msg('Change order opportunity'),
  [NO_FINDING_CATEGORY]: msg('Reading the file'),
});

export const FINDING_CATEGORY_DESCRIPTIONS: Readonly<Record<string, string>> = Object.freeze({
  error: msg('Would be objectively wrong.'),
  omission: msg('Work the bill needs, or says is paid separately, for which no position pays.'),
  inconsistency: msg('Two or more positions contradict each other.'),
  ambiguity: msg('A description leaves open what to do or supply.'),
  risk: msg('Clear, but may cost the bidder money or time, or lead to a dispute.'),
  change_order_opportunity: msg('The bill admits that conditions or decisions stay open until after award.'),
  [NO_FINDING_CATEGORY]:
    msg('About reading the file (a value that could not be read reliably, an unknown unit, a missing formula result, a total whose rows or rounding cannot be told apart), not about the bill itself.'),
});

/**
 * The filter key of an issue's finding category: the category, or {@link NO_FINDING_CATEGORY}
 * when it has none.
 */
export function findingCategoryKey(category: string | null | undefined): string {
  return category || NO_FINDING_CATEGORY;
}

/** `rank` drives the graded indicator (0 = info ... 4 = critical). */
export const SEVERITY_META: Readonly<Record<string, { label: string; rank: number }>> = Object.freeze({
  critical: { label: msg('Critical'), rank: 4 },
  high: { label: msg('High'), rank: 3 },
  medium: { label: msg('Medium'), rank: 2 },
  low: { label: msg('Low'), rank: 1 },
  info: { label: msg('Info'), rank: 0 },
});

/**
 * Status vocabularies by kind. `tone` selects the status dot colour.
 */
type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'accent';

interface StatusEntry {
  label: string;
  tone: StatusTone;
}

export const STATUS_VOCABULARY = Object.freeze({
  document: {
    stored: { label: msg('Stored'), tone: 'neutral' },
    processed: { label: msg('Processed'), tone: 'success' },
    needs_review: { label: msg('Needs review'), tone: 'warning' },
    failed: { label: msg('Failed'), tone: 'danger' },
  },
  quality: {
    ok: { label: msg('OK'), tone: 'success' },
    needs_review: { label: msg('Needs review'), tone: 'warning' },
    failed: { label: msg('Failed'), tone: 'danger' },
  },
  run: {
    queued: { label: msg('Queued'), tone: 'neutral' },
    running: { label: msg('Running'), tone: 'accent' },
    completed: { label: msg('Completed'), tone: 'success' },
    completed_with_errors: { label: msg('Completed with errors'), tone: 'warning' },
    failed: { label: msg('Failed'), tone: 'danger' },
  },
  run_review: {
    in_progress: { label: msg('In progress'), tone: 'warning' },
    finished: { label: msg('Finished'), tone: 'success' },
  },
  detector: {
    completed: { label: msg('Completed'), tone: 'success' },
    skipped: { label: msg('Skipped'), tone: 'neutral' },
    failed: { label: msg('Failed'), tone: 'danger' },
    stopped: { label: msg('Stopped'), tone: 'warning' },
  },
  review: {
    pending_review: { label: msg('Pending review'), tone: 'neutral' },
    confirmed_error: { label: msg('Confirmed error'), tone: 'danger' },
    false_positive: { label: msg('False positive'), tone: 'neutral' },
    needs_more_information: { label: msg('Needs more information'), tone: 'info' },
    dismissed: { label: msg('Dismissed'), tone: 'neutral' },
    corrected: { label: msg('Corrected'), tone: 'success' },
  },
  health: {
    ok: { label: msg('OK'), tone: 'success' },
  },
} satisfies Record<string, Record<string, StatusEntry>>);

/** @returns the entry with its label translated */
export function statusMeta(kind: keyof typeof STATUS_VOCABULARY, status: string | null | undefined): StatusEntry {
  const entries: Readonly<Record<string, StatusEntry>> | undefined = STATUS_VOCABULARY[kind];
  const meta = status ? entries?.[status] : undefined;
  return meta ? { ...meta, label: t(meta.label) } : { label: humanize(status), tone: 'neutral' };
}

export const ROW_KIND_LABELS = Object.freeze({
  item: msg('Item'),
  section: msg('Section'),
  subtotal: msg('Subtotal'),
  grand_total: msg('Grand total'),
  tax: msg('Tax'),
  gross_total: msg('Gross total'),
  adjustment: msg('Adjustment'),
  carry_forward: msg('Carried forward'),
  summary_line: msg('Summary line'),
  text: msg('Text'),
  blank: msg('Blank'),
});

export const PARSE_STATUS_LABELS = Object.freeze({
  exact: msg('Exact'),
  inferred: msg('Inferred'),
  ambiguous: msg('Ambiguous'),
  failed: msg('Failed'),
  unavailable: msg('Unavailable'),
  not_applicable: msg('Not applicable'),
  marker: msg('Marker'),
});

/** Parse statuses that need no marker in the table preview. */
export const UNREMARKABLE_PARSE_STATUSES = Object.freeze(new Set(['exact', 'not_applicable']));

export const PARSE_STATUS_DESCRIPTIONS: Readonly<Record<string, string>> = Object.freeze({
  inferred: msg('Needed column- or document-level evidence to interpret.'),
  ambiguous: msg('More than one interpretation remained; no value was chosen.'),
  failed: msg('The text did not match the expected type.'),
  unavailable: msg('The source holds no value (for example a formula without a cached result).'),
  marker: msg('A word or sign stands where a number would be; no number was invented.'),
});

/** What a cell with parse status `marker` means (`cell.marker`). */
export const VALUE_MARKER_LABELS: Readonly<Record<string, string>> = Object.freeze({
  nil: msg('Nil: nothing to price, counts as zero.'),
  included_elsewhere: msg('Included elsewhere: priced in another item.'),
  not_applicable: msg('Not applicable: the item does not apply.'),
  by_others: msg('By others: supplied by another party.'),
  rate_only: msg('Rate only: priced as a unit rate only.'),
  lump_sum: msg('Lump sum: the quantity is written as a lump-sum token.'),
  not_offered: msg('Not offered: the bidder gives no price; counts as zero.'),
});

export const EVIDENCE_KIND_LABELS = Object.freeze({
  calculation: msg('Calculation'),
  value: msg('Value'),
  rule: msg('Rule'),
  comparison: msg('Comparison'),
  reference: msg('Reference'),
  note: msg('Note'),
});

export const AUDIT_ACTION_LABELS = Object.freeze({
  document_uploaded: msg('Document uploaded'),
  dataset_created: msg('Dataset created'),
  validation_run_completed: msg('Validation run completed'),
  review_finished: msg('Review finished'),
  review_reopened: msg('Review reopened'),
  issue_reviewed: msg('Issue reviewed'),
  correction_proposed: msg('Correction proposed'),
  correction_applied: msg('Correction applied'),
});

export const DOCUMENT_FORMAT_LABELS = Object.freeze({
  xlsx: 'XLSX',
  csv: 'CSV',
  gaeb_x81: 'GAEB X81',
  gaeb_x83: 'GAEB X83',
  gaeb_x84: 'GAEB X84',
  gaeb_x86: 'GAEB X86',
  gaeb_d81: 'GAEB 90 D81',
  gaeb_d83: 'GAEB 90 D83',
  gaeb_d84: 'GAEB 90 D84',
  gaeb_d86: 'GAEB 90 D86',
  pdf: 'PDF',
  docx: 'Word',
});
