import { describe, expect, it } from 'vitest';
import { matchesSearch } from './textSearch.ts';

describe('matchesSearch', () => {
  it('finds every word in any field, ignoring case and accents', () => {
    expect(matchesSearch('anna müller', ['Müller, Anna'])).toBe(true);
    expect(matchesSearch('MULLER', ['Müller'])).toBe(true);
    expect(matchesSearch('bridge amin', ['Riverside', 'Bridge works', 'Amin'])).toBe(true);
    expect(matchesSearch('bridge larissa', ['Riverside', 'Bridge works', 'Amin'])).toBe(false);
  });

  it('matches everything for an empty or blank query, and skips missing fields', () => {
    expect(matchesSearch('', [])).toBe(true);
    expect(matchesSearch('   ', ['x'])).toBe(true);
    expect(matchesSearch('x', [null, undefined, 'X-ray'])).toBe(true);
  });
});
