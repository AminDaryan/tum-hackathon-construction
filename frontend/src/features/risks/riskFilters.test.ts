import { describe, expect, it } from 'vitest';
import { lineTotalIssue, outlierIssue, riskReport } from '../../test/fixtures.ts';
import {
  candidateRisks,
  DEFAULT_RISK_FILTERS,
  filterOptions,
  hasRiskFilters,
  statusCounts,
  visibleRisks,
  type RiskFilters,
} from './riskFilters.ts';
import type { Risk } from '../../services/apiTypes.ts';

const issues = new Map([lineTotalIssue, { ...outlierIssue, review_status: 'false_positive' }].map((issue) => [issue.issue_id, issue]));
const ids = (risks: Risk[]) => risks.map((risk) => risk.risk_id);
const filters = (changes: Partial<RiskFilters>): RiskFilters => ({ ...DEFAULT_RISK_FILTERS, ...changes });

describe('riskFilters', () => {
  it('starts from the main list and adds the record only when asked', () => {
    expect(ids(candidateRisks(riskReport, false))).toEqual(['risk_total', 'risk_price', 'risk_soil']);
    expect(ids(candidateRisks(riskReport, true))).toHaveLength(4);
    expect(candidateRisks(null, true)).toEqual([]);
  });

  it('lists the record when every reminder of the bill was kept in it', () => {
    const recordOnly = { ...riskReport, risks: [], record: riskReport.risks };
    expect(ids(candidateRisks(recordOnly, false))).toEqual(['risk_total', 'risk_price', 'risk_soil']);
    expect(ids(candidateRisks(recordOnly, true))).toEqual(['risk_total', 'risk_price', 'risk_soil']);
  });

  it('filters by status and counts each status with the other filters applied', () => {
    const all = candidateRisks(riskReport, false);
    expect(ids(visibleRisks(all, filters({}), issues))).toEqual(['risk_total', 'risk_price', 'risk_soil']);
    expect(ids(visibleRisks(all, filters({ status: 'open' }), issues))).toEqual(['risk_total', 'risk_soil']);
    expect(ids(visibleRisks(all, filters({ status: 'rejected' }), issues))).toEqual(['risk_price']);
    expect(statusCounts(all, filters({}), issues)).toEqual({ all: 3, open: 2, in_review: 0, approved: 0, rejected: 1 });
    expect(statusCounts(all, filters({ classification: 'error' }), issues)).toEqual({
      all: 1,
      open: 1,
      in_review: 0,
      approved: 0,
      rejected: 0,
    });
    // A risk without a finding takes the status of its own review.
    const reviews = new Map([['risk_soil', 'in_review']]);
    expect(ids(visibleRisks(all, filters({ status: 'in_review' }), issues, reviews))).toEqual(['risk_soil']);
    expect(statusCounts(all, filters({}), issues, reviews)).toMatchObject({ open: 1, in_review: 1 });
  });

  it('searches every word in any order, case-insensitive', () => {
    const all = candidateRisks(riskReport, false);
    expect(ids(visibleRisks(all, filters({ status: 'all', search: 'CLASS soil' }), issues))).toEqual(['risk_soil']);
    expect(ids(visibleRisks(all, filters({ status: 'all', search: '01.001 unit' }), issues))).toEqual(['risk_price']);
  });

  it('filters by tier, classification, type, section and money', () => {
    const all = candidateRisks(riskReport, true);
    const all_ = (changes: Partial<RiskFilters>) => ids(visibleRisks(all, filters({ status: 'all', ...changes }), issues));
    expect(all_({ tier: 'high' })).toEqual(['risk_total']);
    expect(all_({ classification: 'ambiguity' })).toEqual(['risk_soil']);
    expect(all_({ type: 'Arithmetic' })).toEqual(['risk_total']);
    expect(all_({ type: 'Soil class of 01 not stated' })).toEqual(['risk_soil']);
    expect(all_({ section: '01' })).toEqual(['risk_total', 'risk_price', 'risk_soil']);
    expect(all_({ money: 'some' })).toEqual(['risk_total']);
    expect(all_({ money: '1000' })).toEqual([]);
  });

  it('knows when a filter narrows the list and offers the values present', () => {
    expect(hasRiskFilters(DEFAULT_RISK_FILTERS)).toBe(false);
    expect(hasRiskFilters(filters({ money: 'some' }))).toBe(true);
    expect(hasRiskFilters(filters({ search: '  ' }))).toBe(false);
    const options = filterOptions(candidateRisks(riskReport, true), filters({ classification: 'omission' }), issues);
    expect(options.tiers).toEqual(['high', 'medium', 'low']);
    expect(options.classifications).toEqual(['error', 'omission', 'ambiguity', 'risk']);
    expect(options.types).toContain('Arithmetic');
    expect(options.sections).toEqual(['01']);
  });
});
