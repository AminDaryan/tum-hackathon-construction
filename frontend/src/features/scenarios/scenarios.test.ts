import { describe, expect, it } from 'vitest';
import { matchesMaterial } from '../materials/materialMatching.ts';
import { columns, rows, table } from '../../test/fixtures.ts';
import type { Cell, Column } from '../../services/apiTypes.ts';
import { evaluateScenario, scenarioPositions, type ScenarioInput } from './scenarios.ts';

const position = (key: string, extra: Partial<ScenarioInput> = {}): ScenarioInput => ({ key, quantity: '3', unitPrice: '12.35', lineTotal: '37.05',
  discount: null, included: true, currencies: ['EUR'], ...extra });

describe('bill-wide scenarios', () => {
  it('matches literal whole words and phrases, not substrings, synonyms or empty queries', () => {
    expect(matchesMaterial('Structural STEEL, S355', 'steel')).toBe(true);
    expect(matchesMaterial('Beton C30/37', 'c30/37')).toBe(true);
    expect(matchesMaterial('Stahlbeton', 'Beton')).toBe(false);
    expect(matchesMaterial('Steelwork', 'steel')).toBe(false);
    expect(matchesMaterial('Stahl S355', 'steel')).toBe(false);
    expect(matchesMaterial('Steel', '')).toBe(false);
    expect(matchesMaterial('C30/37', 'C30/30')).toBe(false);
  });

  it('sums every table but never summary or excluded rows, using long specifications as evidence', () => {
    // The fixture bill has an item row.
    const item = rows.find((row) => row.classification.kind === 'item')!;
    const tables = [table, { ...table, table_id: 'second' }].map((entry) => ({ ...entry,
      // Test column and cell: only what scenarioPositions reads.
      columns: [...columns, { column_id: 'spec', mapped_semantic_field: 'long_description' } as Column],
      rows: [...rows, { ...item, row_id: 'excluded', excluded: true }].map((row) => ({ ...row, cells: { ...row.cells, spec: { raw_value: 'Steel S355' } as Cell } })),
    }));
    const positions = scenarioPositions(tables);
    expect(positions).toHaveLength(2);
    expect(new Set(positions.map((row) => row.key)).size).toBe(2);
    expect(positions.every((row) => matchesMaterial(row.text, 'steel'))).toBe(true);
  });

  it('compounds exact string percentages, rounds discounted lines, swaps an optional item and leaves inputs untouched', () => {
    const positions = [position('steel', { discount: '10', lineTotal: '33.35' }),
      position('concrete', { quantity: '2', unitPrice: '100', lineTotal: '200' }),
      position('alternative', { included: false, quantity: '1', unitPrice: '27.13', lineTotal: '27.13' })];
    const original = JSON.stringify(positions);
    const rules = [{ keys: ['steel'], percent: '15' }, { keys: ['concrete'], percent: '-5' }];
    const priced = evaluateScenario(positions, rules);
    expect(priced.before).toBe('233.35');
    expect(priced.after).toBe('228.35'); // steel 42.61, less 10% = 38.35; concrete = 190
    expect(priced.change).toBe('-5.00');
    expect(priced.rows[0].price).toBe('14.2025');
    const swapped = evaluateScenario(positions, rules, { steel: false, alternative: true });
    expect(swapped.before).toBe('233.35');
    expect(swapped.after).toBe('217.13');
    expect(swapped.change).toBe('-16.22');
    expect(swapped.rows.map((row) => row.change)).toEqual(['-33.35', '-10.00', '27.13']);
    const compound = evaluateScenario([position('a')], [{ keys: ['a'], percent: '15' }, { keys: ['a'], percent: '-5' }]);
    expect(compound.rows[0].price).toBe('13.492375');
    expect(compound.after).toBe('40.48');
    expect(JSON.stringify(positions)).toBe(original);
  });

  it('does not lose cents beyond Number precision and supports the −100% boundary', () => {
    const positions = [position('large', { quantity: '1', unitPrice: '9007199254740993.01', lineTotal: '9007199254740993.01' }), position('cent', { quantity: '1', unitPrice: '0.02', lineTotal: '0.02' })];
    expect(evaluateScenario(positions, []).before).toBe('9007199254740993.03');
    expect(evaluateScenario(positions, [{ keys: ['large', 'cent'], percent: '-100' }]).after).toBe('0.00');
    expect(evaluateScenario(positions, [{ keys: ['large'], percent: '-100.01' }]).complete).toBe(false);
  });

  it('withholds misleading totals for ambiguous or incomplete evidence', () => {
    for (const positions of [[], [position('a', { included: null })], [position('a', { quantity: null, unitPrice: null, lineTotal: null })],
      [position('a'), position('b', { currencies: ['USD'] })], [position('a'), position('b', { currencies: [] })]]) {
      expect(evaluateScenario(positions, []).before).toBeNull();
    }
    const mismatched = evaluateScenario([position('a', { lineTotal: '40.00' })], [{ keys: ['a'], percent: '15' }]);
    expect(mismatched.complete).toBe(false);
    expect(mismatched.after).toBeNull();
    expect(mismatched.rows[0].reliable).toBe(false);
  });
});
