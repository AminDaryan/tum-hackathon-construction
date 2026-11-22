/**
 * The filters of the Risks tab, applied on the client to the risks of the report: status
 * (open, in review, approved, rejected, all), a search over titles, positions and quotes,
 * priority, classification (the six finding categories), type, section, money at stake, and
 * whose task it is (`assignee`: everyone, the
 * reviewer of this browser, or nobody; applied with the tasks in the Risks tab). The record (the reminders the report keeps out
 * of its main list) is shown only when asked for. `reviews` maps the risks without a finding to
 * the status of their risk review.
 */
import { msg } from '../../i18n/messages.ts';
import type { Risk, RiskReport } from '../../services/apiTypes.ts';
import { compareDecimal, parseDecimal } from '../../utils/decimal.ts';
import { FINDING_CATEGORY_ORDER } from '../../utils/vocabulary.ts';
import {
  classificationOf,
  moneyMagnitude,
  RISK_STATUS_ORDER,
  riskSearchText,
  riskSections,
  riskStatus,
  shortTitle,
  TIER_ORDER,
  type IssuesById,
  type RiskStatus,
} from './riskModel.ts';

export interface RiskFilters {
  status: 'all' | 'open' | 'in_review' | 'approved' | 'rejected';
  search: string;
  tier: string;
  classification: string;
  type: string;
  section: string;
  money: 'any' | 'some' | '1000' | '10000';
  includeRecord: boolean;
  overdueOnly: boolean;
  assignee: '' | 'me' | 'none';
}

export const DEFAULT_RISK_FILTERS: Readonly<RiskFilters> = Object.freeze({
  status: 'all',
  search: '',
  tier: '',
  classification: '',
  type: '',
  section: '',
  money: 'any',
  includeRecord: false,
  overdueOnly: false,
  assignee: '',
});

export const RISK_STATUS_FILTERS = Object.freeze<{ value: RiskFilters['status']; label: string }[]>([
  Object.freeze({ value: 'all', label: msg('All') }),
  Object.freeze({ value: 'open', label: msg('Open') }),
  Object.freeze({ value: 'in_review', label: msg('In review') }),
  Object.freeze({ value: 'approved', label: msg('Approved') }),
  Object.freeze({ value: 'rejected', label: msg('Rejected') }),
]);

export const MONEY_FILTERS = Object.freeze<{ value: RiskFilters['money']; label: string }[]>([
  Object.freeze({ value: 'any', label: msg('Any') }),
  Object.freeze({ value: 'some', label: msg('With an amount') }),
  Object.freeze({ value: '1000', label: msg('1,000 or more') }),
  Object.freeze({ value: '10000', label: msg('10,000 or more') }),
]);

/** The six categories in the report's order, findings about reading the file last. */
function rank(classification: string) {
  const index = FINDING_CATEGORY_ORDER.indexOf(classification);
  return index >= 0 ? index : FINDING_CATEGORY_ORDER.length;
}

function words(search: string) {
  return search.toLowerCase().split(/\s+/).filter(Boolean);
}

function matchesMoney(risk: Risk, money: RiskFilters['money']) {
  if (money === 'any') return true;
  const magnitude = moneyMagnitude(risk.money);
  if (!magnitude) return false;
  if (money === 'some') return true;
  // '1000' and '10000' always parse.
  return compareDecimal(magnitude, parseDecimal(money)!) >= 0;
}

type Reviews = ReadonlyMap<string, string> | undefined;

function matchesStatus(
  risk: Risk,
  status: RiskFilters['status'],
  issuesById: IssuesById | null | undefined,
  reviews: Reviews,
) {
  return status === 'all' || riskStatus(risk, issuesById, reviews) === status;
}

function matchesOthers(risk: Risk, filters: RiskFilters, issuesById: IssuesById | null | undefined) {
  const text = filters.search ? `${riskSearchText(risk)} ${shortTitle(risk, issuesById).toLowerCase()}` : '';
  return (
    words(filters.search).every((word) => text.includes(word)) &&
    (!filters.tier || risk.tier === filters.tier) &&
    (!filters.classification || classificationOf(risk, issuesById) === filters.classification) &&
    (!filters.type || shortTitle(risk, issuesById) === filters.type) &&
    (!filters.section || riskSections(risk).includes(filters.section)) &&
    matchesMoney(risk, filters.money)
  );
}

/**
 * The report's main list; when it is empty, its record. A bill whose every reminder was kept in
 * the record (open questions, low-impact doubts) still lists them, so its list, its count and
 * the risks its cells open agree instead of the list saying nothing was found.
 */
export function mainRisks(report: RiskReport | null | undefined): Risk[] {
  if (!report) return [];
  return [...(report.risks?.length ? report.risks : (report.record ?? []))];
}

/** The risks the list starts from: the main list, plus the record when asked for. */
export function candidateRisks(report: RiskReport | null | undefined, includeRecord: boolean): Risk[] {
  if (!report) return [];
  return includeRecord ? [...(report.risks ?? []), ...(report.record ?? [])] : mainRisks(report);
}

/**
 * @param risks the candidates, in the report's order
 */
export function visibleRisks(
  risks: Risk[],
  filters: RiskFilters,
  issuesById: IssuesById | null | undefined,
  reviews?: ReadonlyMap<string, string>,
): Risk[] {
  return risks.filter(
    (risk) => matchesStatus(risk, filters.status, issuesById, reviews) && matchesOthers(risk, filters, issuesById),
  );
}

/** Counts for the status chips, with the other filters applied. */
export function statusCounts(
  risks: Risk[],
  filters: RiskFilters,
  issuesById: IssuesById | null | undefined,
  reviews?: ReadonlyMap<string, string>,
): Record<'all' | RiskStatus, number> {
  const counts = Object.fromEntries(['all', ...RISK_STATUS_ORDER].map((status) => [status, 0])) as Record<
    'all' | RiskStatus,
    number
  >;
  for (const risk of risks) {
    if (!matchesOthers(risk, filters, issuesById)) continue;
    counts.all += 1;
    counts[riskStatus(risk, issuesById, reviews)] += 1;
  }
  return counts;
}

/** Whether any filter other than the status narrows the list. */
export function hasRiskFilters(filters: RiskFilters): boolean {
  return Boolean(
    filters.search.trim() ||
      filters.tier ||
      filters.classification ||
      filters.type ||
      filters.section ||
      filters.money !== 'any' ||
      filters.overdueOnly ||
      filters.assignee,
  );
}

/** The values present among the risks, for the filter menus (a chosen value always stays). */
export function filterOptions(risks: Risk[], filters: RiskFilters, issuesById: IssuesById | null | undefined) {
  const collect = (pick: (risk: Risk) => (string | null | undefined)[], chosen: string) => {
    const values = new Set(risks.flatMap(pick).filter((value): value is string => Boolean(value)));
    if (chosen) values.add(chosen);
    return [...values];
  };
  const tiers = collect((risk) => [risk.tier], filters.tier).sort(
    (a, b) => TIER_ORDER.indexOf(a as Risk['tier']) - TIER_ORDER.indexOf(b as Risk['tier']),
  );
  return {
    tiers,
    classifications: collect((risk) => [classificationOf(risk, issuesById)], filters.classification).sort(
      (a, b) => rank(a) - rank(b),
    ),
    types: collect((risk) => [shortTitle(risk, issuesById)], filters.type).sort((a, b) => a.localeCompare(b)),
    sections: collect(riskSections, filters.section).sort(),
  };
}
