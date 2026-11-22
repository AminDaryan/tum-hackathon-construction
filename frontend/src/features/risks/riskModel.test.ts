import { describe, expect, it } from 'vitest';
import { lineTotalIssue, outlierIssue, riskReport } from '../../test/fixtures.ts';
import {
  classificationLabel,
  classificationOf,
  findingsOf,
  isOpenStatus,
  moneyMagnitude,
  moneyView,
  plainExplanation,
  positionsText,
  riskMethods,
  riskOfIssue,
  riskSearchText,
  riskStatus,
  riskTarget,
  riskTouchesRow,
  sectionOf,
  shortTitle,
  shownFinding,
} from './riskModel.ts';
import { decimalToString } from '../../utils/decimal.ts';
import type { RiskMoney, ValidationIssue } from '../../services/apiTypes.ts';

const [totalRisk, priceRisk, soilRisk] = riskReport.risks;
const byId = (...issues: ValidationIssue[]) => new Map(issues.map((issue) => [issue.issue_id, issue]));

describe('riskModel', () => {
  it('derives the status of a risk from its findings, or from its own review without one', () => {
    const pending = byId(lineTotalIssue);
    expect(riskStatus(totalRisk, pending)).toBe('open');
    expect(riskStatus(totalRisk, byId({ ...lineTotalIssue, review_status: 'confirmed_error' }))).toBe('approved');
    expect(riskStatus(totalRisk, byId({ ...lineTotalIssue, review_status: 'corrected' }))).toBe('approved');
    expect(riskStatus(totalRisk, byId({ ...lineTotalIssue, review_status: 'false_positive' }))).toBe('rejected');
    expect(riskStatus(totalRisk, byId({ ...lineTotalIssue, review_status: 'needs_more_information' }))).toBe('in_review');
    // A finding that is not loaded yet keeps the risk open.
    expect(riskStatus(totalRisk, new Map())).toBe('open');
    // A risk without a finding: open until its review says otherwise; an unknown status is open.
    expect(riskStatus(soilRisk, pending)).toBe('open');
    expect(riskStatus(soilRisk, pending, new Map([['risk_soil', 'rejected']]))).toBe('rejected');
    expect(riskStatus(soilRisk, pending, new Map([['risk_soil', 'later']]))).toBe('open');
    expect(isOpenStatus('in_review')).toBe(true);
    expect(isOpenStatus('approved')).toBe(false);
  });

  it('classifies a risk by its findings, else by its report category', () => {
    expect(classificationOf(totalRisk, byId(lineTotalIssue))).toBe('error');
    expect(classificationOf(priceRisk, byId(outlierIssue))).toBe('risk');
    expect(classificationOf(soilRisk, new Map())).toBe('ambiguity');
    expect(classificationOf({ ...soilRisk, category: 'trade_interface' }, new Map())).toBe('omission');
    expect(classificationOf({ ...soilRisk, category: 'pricing' }, new Map())).toBe('risk');
    expect(classificationLabel('ambiguity')).toBe('Ambiguity');
  });

  it('gives a short title that names the kind of risk, and a plain explanation', () => {
    expect(shortTitle({ ...soilRisk, risk_type: 'R010' }, new Map())).toBe('Unclear soil class');
    const other = { ...soilRisk, risk_type: 'other', risk_name: 'Other risk' };
    expect(shortTitle(other, new Map())).toBe('Soil class of 01 not stated');
    expect(shortTitle({ ...other, source_issue_ids: ['iss_1'] }, byId(lineTotalIssue))).toBe('Arithmetic');
    expect(shortTitle({ ...other, title: 'Missing unit: row 280 has no unit' }, new Map())).toBe('Missing unit');
    expect(plainExplanation('Found by a wording check: the text says ca.')).toBe('The text says ca.');
    expect(plainExplanation(null)).toBe('');
  });

  it('says money in words: exact, estimate, comparison and unknown (never a number for unknown)', () => {
    expect(moneyView(totalRisk.money)).toMatchObject({ kind: 'exact', text: '20.00 EUR' });
    expect(moneyView({ kind: 'exact', amount: '9938.4', currency: 'EUR' } as RiskMoney).text).toBe('9,938.40 EUR');
    // Test amounts: only what the view reads.
    expect(moneyView({ kind: 'estimate', low: '0', high: '2640.00', currency: 'EUR' } as RiskMoney)).toMatchObject({
      kind: 'estimate',
      text: '0.00 to 2,640.00 EUR (estimate)',
    });
    expect(moneyView(priceRisk.money)).toMatchObject({
      kind: 'reference',
      text: 'Comparison: 300.00 EUR',
      note: 'Not a loss: the price may be right.',
    });
    expect(moneyView(soilRisk.money)).toEqual({ kind: 'unknown', text: 'Not known', note: 'The positions concerned are a medium share of the bill', basis: null });
    expect(moneyView(null).text).toBe('Not known');
  });

  it('orders money by the exact amount or the larger end of an estimate', () => {
    // Test amounts: only what the magnitude reads.
    expect(decimalToString(moneyMagnitude({ kind: 'exact', amount: '-540.00' } as RiskMoney)!)).toBe('540.00');
    expect(decimalToString(moneyMagnitude({ kind: 'estimate', low: '-3000', high: '100' } as RiskMoney)!)).toBe('3000');
    expect(moneyMagnitude(priceRisk.money)).toBeNull();
  });

  it('names positions, sections, methods and categories', () => {
    expect(positionsText({ positions: [{ label: 'a' }, { label: 'b' }, { label: 'c' }, { label: 'd' }], positions_total: 6 })).toBe(
      'a, b, c and 3 more',
    );
    expect(positionsText({ positions: [] })).toBe('');
    expect(sectionOf('03.02.0017')).toBe('03');
    expect(sectionOf('01')).toBe('01');
    expect(sectionOf('Titel')).toBeNull();
    expect(riskMethods({ methods: ['invariant', 'dependency', 'vagueness', 'guided_llm'] })).toEqual([
      'Rule',
      'Text check',
      'Language model',
    ]);
  });

  it('finds where a risk is: its finding cell first, else its first position', () => {
    expect(riskTarget(totalRisk, lineTotalIssue)).toEqual({ tableId: 'tbl_1', rowId: 'row_5', columnId: 'col_total' });
    expect(riskTarget(soilRisk, null)).toEqual({ tableId: 'tbl_1', rowId: 'row_4', columnId: 'col_text' });
    expect(riskTarget(riskReport.record[0], null)).toBeNull();
    expect(riskTouchesRow(soilRisk, 'row_4', new Map())).toBe(true);
    expect(riskTouchesRow(priceRisk, 'row_4', byId(outlierIssue))).toBe(false);
  });

  it('connects findings and risks, and picks the finding to show', () => {
    const issues = byId(lineTotalIssue, outlierIssue);
    expect(riskOfIssue(riskReport.risks, 'iss_2')).toBe(priceRisk);
    expect(riskOfIssue(riskReport.risks, 'iss_9')).toBeNull();
    expect(findingsOf(totalRisk, issues)).toEqual([lineTotalIssue]);
    const twoFindings = { ...totalRisk, source_issue_ids: ['iss_1', 'iss_2'] };
    const decided = byId({ ...lineTotalIssue, review_status: 'confirmed_error' }, outlierIssue);
    expect(shownFinding(twoFindings, decided)!.issue_id).toBe('iss_2');
    expect(shownFinding(twoFindings, decided, 'iss_1')!.issue_id).toBe('iss_1');
  });

  it('searches titles, names, positions and quotes', () => {
    expect(riskSearchText({ ...soilRisk, quotes: [{ position: null, source: 'text', text: 'Bodenklasse' }] })).toContain('bodenklasse');
    expect(riskSearchText(soilRisk)).toContain('01');
  });
});
