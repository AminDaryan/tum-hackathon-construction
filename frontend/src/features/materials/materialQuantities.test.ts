import { afterEach, expect, test, vi } from 'vitest';
import { applyLanguage } from '../../i18n/messages.ts';
import type { Row, TableSummary } from '../../services/apiTypes.ts';
import { supplierEmailDraft } from '../email/emailDraft.ts';
import { loadMaterialQuantities } from './loadMaterialQuantities.ts';
import { materialQuantities, materialQuantitiesCsv, mergeMaterialGroups } from './materialQuantities.ts';

vi.mock('../../services/datasetsService.ts', () => ({ getTableRows: vi.fn() }));
import { getTableRows } from '../../services/datasetsService.ts';

const fields = ['item_code', 'description', 'long_description', 'quantity', 'unit', 'unit_price'];
// Test table and rows: only what the grouping reads.
const table = { table_id: 't', name: 'Bill', columns: fields.map((field) => ({ column_id: field, mapped_semantic_field: field })) } as TableSummary;
const row = (id: string, description: string, quantity: string | null, unit = 'm³', long = ''): Row => ({
  row_id: id, source_row_number: Number(id), classification: { kind: 'item', counts_toward_totals: true },
  cells: Object.fromEntries(Object.entries({ item_code: id, description, long_description: long, quantity, unit }).map(([field, value]) => [field, {
    raw_value: value, normalized_value: field === 'quantity' ? { kind: 'number', value } : null,
  }])),
}) as Row;
// Test classifications: only the fields the grouping reads.
const classified = (classification: Partial<Row['classification']>) => classification as Row['classification'];
afterEach(() => applyLanguage('en'));

test('totals exact spec and unit across bill tables, with every contributing position', () => {
  const { groups } = materialQuantities([
    { table, rows: [row('1', 'Concrete C25/30', '0.1'), row('2', 'Concrete C25/30', '0.2')] },
    { table: { ...table, table_id: 't2' }, rows: [row('3', 'Concrete C25/30', '12.45')] },
  ]);
  expect(groups).toHaveLength(1);
  expect(groups[0].quantity).toBe('12.75');
  expect(groups[0].positions.map((p) => [p.tableId, p.code, p.quantity])).toEqual([['t', '1', '0.1'], ['t', '2', '0.2'], ['t2', '3', '12.45']]);
});

test('never conflates grades, units, long specs, section context or clipped text', () => {
  const section = { ...row('90', 'Exposure XC4', '0'), classification: classified({ kind: 'section' }) };
  const rows = [
    row('1', 'Concrete C25/30', '10'), row('2', 'Concrete C30/37', '20'),
    row('3', 'Concrete C25/30', '30', 'm²'), row('4', 'Concrete C25/30', '40', 'm³', 'XC2'),
    row('5', 'Concrete C25/30', '50', 'm³', 'XC4'),
    { ...row('6', 'Concrete C25/30', '60'), section_path: ['90'] }, section,
    row('7', 'DN150 pipe', '70', 'm'), row('8', 'DN100 pipe', '80', 'm'),
    row('9', 'Concrete…', '90'), row('10', 'Concrete…', '100'),
  ];
  expect(materialQuantities([{ table, rows }]).groups).toHaveLength(10);
});

test('omits excluded, ambiguous, optional and non-item rows without treating missing quantities as zero', () => {
  const rows = [
    { ...row('1', 'Concrete', '1'), excluded: true },
    { ...row('2', 'Concrete', '2'), classification: classified({ kind: 'item', counts_toward_totals: null }) },
    { ...row('3', 'Concrete', '3'), classification: classified({ kind: 'item', counts_toward_totals: false }) },
    { ...row('4', 'Concrete', '4'), classification: classified({ kind: 'subtotal' }) },
    row('5', 'Concrete', null), row('6', 'Concrete', '6', ''), row('7', '', '7'),
    { ...row('8', 'Concrete', '8'), classification: classified({ kind: 'item', counts_toward_totals: true, not_counted_above_section_id: 's' }) },
    row('9', 'Concrete', '0'), row('10', 'Concrete', '-0.125'),
  ];
  const result = materialQuantities([{ table, rows }]);
  expect(result.skipped).toBe(7);
  expect(result.groups[0].quantity).toBe('-0.125');
  expect(result.groups[0].positions).toHaveLength(2);
});

test('reviewer merge preserves specs and sources, rejects mixed units, and exports safe CSV', () => {
  const { groups } = materialQuantities([{ table, rows: [row('1', '=Concrete "A"', '1.25'), row('2', 'Concrete B', '4.5'), row('3', 'Pipe', '7', 'm')] }]);
  expect(mergeMaterialGroups(groups, new Set(groups.map((g) => g.id)))).toBe(groups);
  const merged = mergeMaterialGroups(groups, new Set(groups.slice(0, 2).map((g) => g.id)));
  expect(merged).toHaveLength(2);
  expect(merged[0].quantity).toBe('5.75');
  expect(merged[0].reviewed).toBe(true);
  expect(merged[0].positions.map((p) => p.description)).toEqual(['=Concrete "A"', 'Concrete B']);
  const csv = materialQuantitiesCsv(merged);
  expect(csv).toContain('"\'=Concrete ""A""","5.75","m³","yes"');
  expect(csv).toContain('Bill / 2 / 2 / 4.5 m³');
  expect(csv.match(/"5.75"/g)).toHaveLength(1);
  const draft = supplierEmailDraft({ groups: merged, billName: 'Fictitious bill' });
  expect(draft.body).toContain('5.75 m³');
  expect(draft.body).toContain('Concrete B');
  expect(draft.body).toContain('Bill / 2: 4.5 m³');
  expect(draft.body).toContain('Please confirm equivalence');
  applyLanguage('de');
  expect(supplierEmailDraft({ groups: merged, billName: 'Test' }).subject).toBe('Lieferantenpreisanfrage: Test');
});

test('loads all pages of every table, including the final position of a 9000-item bill', async () => {
  vi.mocked(getTableRows).mockImplementation(async (_dataset, tableId, { offset = 0, limit = 100 } = {}) => {
    const total = tableId === 't' ? 9000 : 1;
    return { offset, limit, total, items: Array.from({ length: Math.min(limit, total - offset) }, (_, i) => row(String(offset + i + 1), 'DN150 pipe', '0.1', 'm')) };
  });
  const result = await loadMaterialQuantities({ dataset_id: 'd', tables: [table, { ...table, table_id: 't2' }] }, new AbortController().signal);
  expect(result.groups).toHaveLength(1);
  expect(result.groups[0].quantity).toBe('900.1');
  expect(result.groups[0].positions).toHaveLength(9001);
  vi.mocked(getTableRows).mockResolvedValue({ items: [], total: 1, offset: 0, limit: 1000 });
  await expect(loadMaterialQuantities({ dataset_id: 'd', tables: [table] })).rejects.toThrow('Incomplete table');
});
