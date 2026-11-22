/**
 * Conservative, bill-wide quantity grouping, independent of React and of price matching.
 * Reuse this module for scenarios: no fuzzy matching, unit conversion or inferred material
 * extraction. The complete supplied specification and enclosing section text must match.
 * A reviewer may explicitly merge groups, but never across units. Quantities stay decimal.
 */
import { decimalToString, parseDecimal, subtractDecimal, type Decimal } from '../../utils/decimal.ts';
import type { Row, TableSummary } from '../../services/apiTypes.ts';
import { priceFacts } from '../risks/pricing.ts';

/** One bill position counted in a group. */
export interface MaterialPosition {
  id: string;
  tableId: string;
  tableName: string;
  rowId: string;
  rowNumber: number;
  code: string | null;
  description: string;
  specification: string;
  context: string;
  quantity: string | null;
}

/** Positions with the same specification, section context and unit, and their total. */
export interface MaterialGroup {
  id: string;
  description: string;
  unit: string;
  quantity: string;
  positions: MaterialPosition[];
  /** a reviewer merged it */
  reviewed: boolean;
}

/** A table of the bill with all its rows. */
export interface MaterialTable {
  table: TableSummary;
  rows: Row[];
}

const NON_SPEC = new Set(['item_code', 'quantity', 'unit', 'unit_price', 'line_total', 'discount_percent']);
const text = (value: unknown) => String(value ?? '').trim().replace(/\s+/g, ' ');
const add = (a: Decimal, b: Decimal) => subtractDecimal(a, { ...b, units: -b.units });

function specification(row: Row, table: TableSummary): [string, string][] {
  return table.columns
    .filter((column) => !NON_SPEC.has(column.mapped_semantic_field ?? ''))
    .map((column): [string, string] => [column.mapped_semantic_field ?? column.normalized_name ?? column.column_id, text(row.cells?.[column.column_id]?.raw_value)])
    .filter(([, value]) => value);
}

/** Input: all pages of all bill tables, as [{ table, rows }]. Never pass just visible rows. */
export function materialQuantities(tables: readonly MaterialTable[]): { groups: MaterialGroup[]; skipped: number } {
  const groups = new Map<string, MaterialGroup>();
  let skipped = 0;
  for (const { table, rows } of tables) {
    const byId = new Map(rows.map((row) => [row.row_id, row]));
    for (const row of rows) {
      if (row.classification?.kind !== 'item') continue;
      // A row and its table always give facts.
      const facts = priceFacts(row, table)!;
      const quantity = parseDecimal(facts.quantity);
      if (row.excluded || row.classification.counts_toward_totals !== true || row.classification.not_counted_above_section_id || !quantity || !facts.unit || !facts.description) {
        skipped++;
        continue;
      }
      const id = JSON.stringify([table.table_id, row.row_id]);
      const spec = specification(row, table);
      const context = (row.section_path ?? []).map((sectionId): [string, string][] => {
        const section = byId.get(sectionId);
        return section ? specification(section, table) : [['unresolved', sectionId]];
      });
      // Clipped text is not evidence of equality. Retain each such position on its own.
      const uncertain = [...spec, ...context.flat()].some(([, value]) => /…|\.{3}/.test(value));
      const key = JSON.stringify([spec, context, facts.unit, uncertain ? id : null]);
      const position: MaterialPosition = {
        id, tableId: table.table_id, tableName: table.name, rowId: row.row_id,
        rowNumber: row.source_row_number, code: facts.itemCode, description: facts.description,
        specification: spec.map(([, value]) => value).join('\n'),
        context: context.flat().map(([, value]) => value).join(' / '),
        quantity: facts.quantity,
      };
      const existing = groups.get(key);
      if (existing) {
        // A group's quantity is a decimal string written here.
        existing.quantity = decimalToString(add(parseDecimal(existing.quantity)!, quantity));
        existing.positions.push(position);
      } else {
        groups.set(key, { id, description: facts.description, unit: facts.unit, quantity: decimalToString(quantity), positions: [position], reviewed: false });
      }
    }
  }
  return { groups: [...groups.values()], skipped };
}

/** An explicit reviewer decision; retaining every source spec makes the merge auditable. */
export function mergeMaterialGroups(groups: MaterialGroup[], ids: ReadonlySet<string>): MaterialGroup[] {
  const selected = groups.filter((group) => ids.has(group.id));
  if (selected.length < 2 || new Set(selected.map((group) => group.unit)).size !== 1) return groups;
  const merged: MaterialGroup = {
    ...selected[0], reviewed: true,
    // Group quantities are decimal strings written above; '0' always parses.
    quantity: decimalToString(selected.reduce((sum, group) => add(sum, parseDecimal(group.quantity)!), parseDecimal('0')!)),
    positions: selected.flatMap((group) => group.positions),
  };
  return groups.flatMap((group) => group.id === merged.id ? [merged] : ids.has(group.id) ? [] : [group]);
}

/** One record per group, so a spreadsheet sum never double-counts a repeated group total. */
export function materialQuantitiesCsv(groups: readonly MaterialGroup[]): string {
  const quote = (value: unknown) => {
    const raw = String(value ?? '');
    const safe = /^[\s]*[=+\-@\t\r]/.test(raw) ? `'${raw}` : raw;
    return `"${safe.replaceAll('"', '""')}"`;
  };
  const rows = [['Material', 'Total quantity', 'Unit', 'Reviewer merged', 'Contributing positions (table / position / source row / quantity)', 'Specifications', 'Section contexts']];
  for (const group of groups) {
    rows.push([
      group.description, group.quantity, group.unit, group.reviewed ? 'yes' : 'no',
      group.positions.map((position) => `${position.tableName} / ${position.code || '—'} / ${position.rowNumber} / ${position.quantity} ${group.unit}`).join('\n'),
      [...new Set(group.positions.map((position) => position.specification))].join('\n\n'),
      [...new Set(group.positions.map((position) => position.context))].filter(Boolean).join('\n'),
    ]);
  }
  return '\uFEFF' + rows.map((row) => row.map(quote).join(',')).join('\r\n') + '\r\n';
}
