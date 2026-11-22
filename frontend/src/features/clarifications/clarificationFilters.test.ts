import { describe, expect, it } from 'vitest';
import { clarificationQuery, hasClarificationFilters, NO_CLARIFICATION_FILTERS } from './clarificationFilters.ts';

const TODAY = new Date(2026, 10, 28, 23, 30); // 28 November 2026, late evening local time

describe('clarificationQuery', () => {
  it('sends no filter while none is chosen', () => {
    expect(clarificationQuery(NO_CLARIFICATION_FILTERS, TODAY)).toEqual({});
    expect(hasClarificationFilters(NO_CLARIFICATION_FILTERS)).toBe(false);
  });

  it('sends the trimmed search and each chosen filter', () => {
    const filters = { search: '  rock layer ', phase: 'bid', kind: 'management', status: 'suggested', due: '' } as const;
    expect(clarificationQuery(filters, TODAY)).toEqual({ search: 'rock layer', phase: 'bid', kind: 'management', status: 'suggested' });
    expect(hasClarificationFilters(filters)).toBe(true);
    expect(hasClarificationFilters({ ...NO_CLARIFICATION_FILTERS, search: '   ' })).toBe(false);
  });

  it('asks for what is needed within a week of the local day, across the month', () => {
    expect(clarificationQuery({ ...NO_CLARIFICATION_FILTERS, due: 'this_week' }, TODAY)).toEqual({ due_by: '2026-12-05' });
  });
});
