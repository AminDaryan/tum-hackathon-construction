import { describe, expect, it } from 'vitest';
import { methodLabel, methodOf } from './methods.ts';

describe('methodOf', () => {
  it('counts rule-based text checks as rules and names language-model checks', () => {
    expect(methodOf('deterministic.line_total', 'deterministic')).toBe('rule');
    expect(methodOf('domain.boq_typos', 'semantic')).toBe('rule');
    expect(methodOf('statistical.peer_price', 'statistical')).toBe('statistics');
    expect(methodOf('llm.titel_review', 'semantic')).toBe('llm');
    // The text-similarity checks of plan step B3 compare positions, they apply no rule.
    expect(methodOf('semantic.unit_fit', 'semantic')).toBe('statistics');
    expect(methodOf('semantic.section_fit', 'semantic')).toBe('statistics');
    expect(methodOf('machine_learning.near_duplicates', 'machine_learning')).toBe('machine_learning');
    expect(methodLabel('statistical.x', undefined)).toBe('Statistics');
    expect(methodLabel('research.isolation_forest', 'research')).toBe('Research');
  });
});
