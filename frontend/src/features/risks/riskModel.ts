/**
 * How the workspace reads the risk report (GET /validation-runs/{run}/risks): the status of a
 * risk, its classification and short title, the words for its method, certainty and category,
 * how its money is said, and where it is in the sheet.
 *
 * A risk with findings (`source_issue_ids`) is decided through its findings. A risk without a
 * finding comes from the text checks of the risk report; its decision is a risk review
 * (GET/PUT /validation-runs/{run}/risk-reviews), passed in as a map of risk id to status.
 */
import { absDecimal, compareDecimal, parseDecimal } from '../../utils/decimal.ts';
import { msg, t } from '../../i18n/messages.ts';
import { formatCount, formatMoney } from '../../utils/format.ts';
import {
  FINDING_CATEGORY_LABELS,
  FINDING_CATEGORY_ORDER,
  humanize as humanizeWords,
  NO_FINDING_CATEGORY,
} from '../../utils/vocabulary.ts';
import { isToReview } from '../workspace/reviewLabels.ts';
import type { Risk, RiskMoney, ValidationIssue } from '../../services/apiTypes.ts';
import type { Decimal } from '../../utils/decimal.ts';

/** The run's findings by issue id. */
export type IssuesById = ReadonlyMap<string, ValidationIssue>;

export type RiskStatus = 'open' | 'in_review' | 'approved' | 'rejected';

export const RISK_STATUS_LABELS: Readonly<Record<string, string>> = Object.freeze({
  open: msg('Open'),
  in_review: msg('In review'),
  approved: msg('Approved'),
  rejected: msg('Rejected'),
});

export const RISK_STATUS_ORDER = Object.freeze<RiskStatus[]>(['open', 'in_review', 'approved', 'rejected']);

/** Statuses that still need someone: a decision, or an answer before one. */
const OPEN_STATUSES: ReadonlySet<string> = Object.freeze(new Set(['open', 'in_review']));

const NO_REVIEWS: ReadonlyMap<string, string> = new Map();

/**
 * @param issuesById the run's findings
 * @param reviews risk id to the status of its risk review (risks without
 *   a finding)
 */
export function riskStatus(
  risk: Pick<Risk, 'risk_id' | 'source_issue_ids'>,
  issuesById: IssuesById | null | undefined,
  reviews: ReadonlyMap<string, string> = NO_REVIEWS,
): RiskStatus {
  const ids = risk.source_issue_ids ?? [];
  if (!ids.length) {
    const status = reviews?.get(risk.risk_id);
    return status && RISK_STATUS_LABELS[status] ? (status as RiskStatus) : 'open';
  }
  const findings = findingsOf(risk, issuesById);
  if (!findings.length || findings.some(isToReview)) return 'open';
  if (findings.some((issue) => issue.review_status === 'needs_more_information')) return 'in_review';
  if (findings.some((issue) => issue.review_status === 'confirmed_error' || issue.review_status === 'corrected')) return 'approved';
  return 'rejected';
}

export function isOpenStatus(status: string): boolean {
  return OPEN_STATUSES.has(status);
}

/**
 * The classification of a risk with text checks only: the report's category in the six finding
 * categories. A risk with findings takes its findings' category instead.
 */
const CLASSIFICATION_BY_CATEGORY: Readonly<Record<string, string>> = Object.freeze({
  unclear_description: 'ambiguity',
  standards: 'ambiguity',
  contradiction: 'inconsistency',
  duplicate_scope: 'inconsistency',
  missing_scope: 'omission',
  trade_interface: 'omission',
  data_quality: 'error',
});

/**
 * One of the six finding categories (error, inconsistency, omission, ambiguity, risk, change
 * order opportunity): the first, in that order, among the risk's findings; for a risk without
 * a finding, its report category read as one of them (anything else is a risk).
 */
export function classificationOf(risk: Risk | null | undefined, issuesById: IssuesById | null | undefined): string {
  const findings = findingsOf(risk, issuesById);
  if (findings.length) {
    const categories = new Set<string | null>(findings.map((issue) => issue.finding_category));
    // Findings about reading the file have no category.
    return FINDING_CATEGORY_ORDER.find((category) => categories.has(category)) ?? NO_FINDING_CATEGORY;
  }
  return CLASSIFICATION_BY_CATEGORY[risk?.category ?? ''] ?? 'risk';
}

export function classificationLabel(classification: string): string {
  return t(FINDING_CATEGORY_LABELS[classification] ?? humanizeWords(classification));
}

const SHORT_TITLE_LIMIT = 48;

/**
 * A short title that names the kind of risk: the report's risk name ("Wrong measurement
 * unit"), else the kind of its main finding ("Spelling"), else the title up to its colon.
 */
export function shortTitle(risk: Risk | null | undefined, issuesById: IssuesById | null | undefined): string {
  if (!risk) return '';
  if (risk.risk_type !== 'other' && risk.risk_name) return risk.risk_name;
  const finding = findingsOf(risk, issuesById)[0];
  if (finding?.issue_category) return humanizeWords(finding.issue_category);
  const title = risk.title ?? '';
  const colon = title.indexOf(': ');
  if (colon > 0 && colon <= SHORT_TITLE_LIMIT) return title.slice(0, colon);
  return title;
}

/**
 * The explanation as a plain statement about the bill: a leading "Found by a wording check: "
 * is dropped (the method is shown on its own), and the first letter is capitalized.
 */
export function plainExplanation(text: string | null | undefined): string {
  const trimmed = String(text ?? '').replace(/^Found by [^:]{1,80}:\s*/, '').trim();
  return trimmed ? trimmed.charAt(0).toUpperCase() + trimmed.slice(1) : '';
}

/** The rule of a price-reference finding whose material match the local model suggested. */
const MODEL_MATCH_RULE = 'model_matched_below_published_material_value';

/** Whether a finding rests on a material match the local model suggested (not a person). */
export function isModelSuggested(issue: Pick<ValidationIssue, 'rule_id'> | null | undefined): boolean {
  return issue?.rule_id === MODEL_MATCH_RULE;
}

/** The findings of a risk that are loaded, in the risk's order. */
export function findingsOf(
  risk: Pick<Risk, 'source_issue_ids'> | null | undefined,
  issuesById: IssuesById | null | undefined,
): ValidationIssue[] {
  return (risk?.source_issue_ids ?? [])
    .map((id) => issuesById?.get(id))
    .filter((issue): issue is ValidationIssue => Boolean(issue));
}

const METHOD_WORDS: Readonly<Record<string, string>> = Object.freeze({
  invariant: msg('Rule'),
  dependency: msg('Rule'),
  attribute_consistency: msg('Rule'),
  vagueness: msg('Text check'),
  peer_comparison: msg('Statistics'),
  guided_llm: msg('Language model'),
});

/**
 * @returns distinct method words, e.g. ["Rule", "Text check"]
 */
export function riskMethods(risk: { methods?: string[] }): string[] {
  return [...new Set((risk.methods ?? []).map((method) => METHOD_WORDS[method] ?? humanize(method)))];
}

export const CERTAINTY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  confirmed: msg('Confirmed'),
  suspected: msg('Suspected'),
  semantic: msg('Text signal'),
  unclear: msg('Unclear'),
});

export const CERTAINTY_DESCRIPTIONS: Readonly<Record<string, string>> = Object.freeze({
  confirmed: msg('A rule shows it in the bill.'),
  suspected: msg('A comparison makes it likely; the bill alone cannot prove it.'),
  semantic: msg('The wording points to it.'),
  unclear: msg('The information at hand cannot decide it.'),
});

export const HARM_LABELS: Readonly<Record<string, string>> = Object.freeze({
  money: msg('Money'),
  contract: msg('Contract'),
  schedule: msg('Schedule'),
  safety: msg('Safety'),
  data_quality: msg('Data quality'),
});

export const TIER_ORDER = Object.freeze<Risk['tier'][]>(['critical', 'high', 'medium', 'low', 'info']);

function humanize(value: string | null | undefined) {
  const text = String(value ?? '').replaceAll('_', ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const SIZE_WORDS: Readonly<Record<string, string>> = Object.freeze({
  large: msg('The positions concerned are a large share of the bill'),
  medium: msg('The positions concerned are a medium share of the bill'),
  small: msg('The positions concerned are a small share of the bill'),
});

/**
 * How the money of a risk is said (never a number for unknown money, never a loss for a
 * comparison).
 */
export function moneyView(
  money: RiskMoney | null | undefined,
): { kind: 'exact' | 'estimate' | 'reference' | 'unknown', text: string, note: string | null, basis: string | null } {
  if (!money) return { kind: 'unknown', text: t('Not known'), note: null, basis: null };
  if (money.kind === 'exact' && money.amount != null) {
    return { kind: 'exact', text: formatMoney(money.amount, money.currency), note: null, basis: money.basis ?? null };
  }
  if (money.kind === 'estimate' && (money.low != null || money.high != null)) {
    const text =
      money.low != null && money.high != null
        ? t('{low} to {high} (estimate)', { low: formatMoney(money.low), high: formatMoney(money.high, money.currency) })
        : t('{amount} (estimate)', { amount: formatMoney(money.low ?? money.high, money.currency) });
    return { kind: 'estimate', text, note: null, basis: money.basis ?? null };
  }
  if (money.reference) {
    return {
      kind: 'reference',
      text: t('Comparison: {amount}', { amount: formatMoney(money.reference.amount, money.reference.currency) }),
      note: t('Not a loss: the price may be right.'),
      basis: money.reference.basis ?? null,
    };
  }
  const size = SIZE_WORDS[money.size_class ?? ''];
  return { kind: 'unknown', text: t('Not known'), note: size ? t(size) : null, basis: null };
}

/**
 * The size of the money at stake, for the Money filter: an exact amount by its absolute value,
 * an estimate by the larger absolute end of its range. Comparisons and unknown money have none.
 */
export function moneyMagnitude(money: RiskMoney | null | undefined): Decimal | null {
  if (!money) return null;
  if (money.kind === 'exact') {
    const value = parseDecimal(money.amount);
    return value ? absDecimal(value) : null;
  }
  if (money.kind === 'estimate') {
    const ends = [money.low, money.high]
      .map(parseDecimal)
      .filter((value): value is Decimal => value !== null)
      .map(absDecimal);
    if (!ends.length) return null;
    return ends.reduce((largest, value) => (compareDecimal(value, largest) > 0 ? value : largest));
  }
  return null;
}

/**
 * @returns "03.02.0017, 03.02.0018 and 3 more"; empty when the risk has no position
 */
export function positionsText(
  risk: { positions?: { label: string }[]; positions_total?: number },
  shown: number = 3,
): string {
  const labels = (risk.positions ?? []).map((position) => position.label);
  const total = Math.max(risk.positions_total ?? labels.length, labels.length);
  if (!labels.length) return '';
  const listed = labels.slice(0, shown).join(', ');
  const more = total - Math.min(shown, labels.length);
  return more > 0 ? t('{list} and {count} more', { list: listed, count: formatCount(more) }) : listed;
}

/**
 * The first level of a position number ("03.02.0017" and the title "03" give "03"), for the
 * Section filter.
 */
export function sectionOf(itemCode: string | null | undefined): string | null {
  if (!itemCode) return null;
  const match = String(itemCode).trim().match(/^(\d+)(?:[.\s]|$)/);
  return match ? match[1] : null;
}

/** The sections of a risk's positions. */
export function riskSections(risk: Pick<Risk, 'positions'>): string[] {
  return [...new Set((risk.positions ?? []).map((position) => sectionOf(position.item_code)).filter((section): section is string => Boolean(section)))];
}

/**
 * Whether a risk concerns a row of the sheet: one of its positions, or one of its findings'
 * cells or rows.
 */
export function riskTouchesRow(
  risk: Pick<Risk, 'positions' | 'source_issue_ids'>,
  rowId: string | null | undefined,
  issuesById: IssuesById | null | undefined,
): boolean {
  if (!rowId) return false;
  if ((risk.positions ?? []).some((position) => position.row_id === rowId)) return true;
  return findingsOf(risk, issuesById).some(
    (issue) => issue.row_id === rowId || (issue.affected_cells ?? []).some((cell) => cell.row_id === rowId),
  );
}

/**
 * Where the sheet goes for a risk: its finding's cell when it has one, else the first cell (or
 * row) of its first position.
 */
export function riskTarget(
  risk: Pick<Risk, 'positions'> | null | undefined,
  issue: ValidationIssue | null = null,
): { tableId: string; rowId: string; columnId: string | null } | null {
  const cells = issue?.affected_cells?.length ? issue.affected_cells : (issue?.input_cells ?? []);
  const cell = cells.find((candidate) => candidate.row_id);
  if (cell) return { tableId: cell.table_id, rowId: cell.row_id, columnId: cell.column_id ?? null };
  if (issue?.row_id && issue.table_id) return { tableId: issue.table_id, rowId: issue.row_id, columnId: null };
  const position = (risk?.positions ?? []).find((candidate) => candidate.row_id);
  if (!position) return null;
  const first = (position.cells ?? [])[0];
  return { tableId: position.table_id, rowId: position.row_id, columnId: first?.column_id ?? null };
}

/** The risk that holds a finding, from the main list or the record. */
export function riskOfIssue(risks: Risk[], issueId: string | null | undefined): Risk | null {
  if (!issueId) return null;
  return risks.find((risk) => (risk.source_issue_ids ?? []).includes(issueId)) ?? null;
}

/**
 * The finding of a risk to show: the asked one when it belongs to the risk, else the first one
 * still to review, else the first one.
 */
export function shownFinding(
  risk: Pick<Risk, 'source_issue_ids'> | null | undefined,
  issuesById: IssuesById | null | undefined,
  issueId: string | null = null,
): ValidationIssue | null {
  const findings = findingsOf(risk, issuesById);
  return (
    findings.find((issue) => issue.issue_id === issueId) ?? findings.find((issue) => isToReview(issue)) ?? findings[0] ?? null
  );
}

/** Text of a risk for the search box. */
export function riskSearchText(risk: Risk): string {
  return [
    risk.title,
    risk.risk_name,
    risk.risk_type,
    ...(risk.positions ?? []).map((position) => position.label),
    ...(risk.quotes ?? []).map((quote) => quote.text),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}
