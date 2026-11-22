import { decimalToString, multiplyDecimal, parseDecimal, subtractDecimal, type Decimal } from '../../utils/decimal.ts';
import type { Row, TableSummary } from '../../services/apiTypes.ts';
import { isPriced, lineTotalFor, priceFacts, type PriceFacts } from '../risks/pricing.ts';

const add = (a: Decimal, b: Decimal) => subtractDecimal(a, { ...b, units: -b.units });

/** A bill table with all its rows. */
type ScenarioTable = Pick<TableSummary, 'table_id' | 'name' | 'columns'> & { rows: Row[] };

/** An item row of the bill with its figures, as a scenario sees it. */
interface ScenarioPosition extends PriceFacts {
  key: string;
  /** description, long description, material and specification texts */
  text: string;
  tableName: string;
  /** whether the bill counts it toward the totals; null when unknown */
  included: boolean | null;
  currencies: string[];
}

/** What a scenario reads of a position. */
export type ScenarioInput = Pick<ScenarioPosition, 'key' | 'quantity' | 'unitPrice' | 'lineTotal' | 'discount' | 'included' | 'currencies'>;

/** A unit price change in percent for the positions it froze when added. */
export interface ScenarioRule {
  /** the material or text it was chosen by; empty for a manual selection */
  query?: string;
  percent: string;
  keys: string[];
}

/** Only item rows, across every table; never sum subtotal, recap or tax rows twice. */
export function scenarioPositions(tables: readonly ScenarioTable[]): ScenarioPosition[] {
  return tables.flatMap((table) => table.rows.filter((row) => row.classification?.kind === 'item' && !row.excluded).map((row) => {
    // A row and its table always give facts.
    const facts = priceFacts(row, table)!;
    const text = table.columns.filter((column) => ['description', 'long_description', 'material', 'specification'].includes(column.mapped_semantic_field ?? ''))
      .map((column) => row.cells[column.column_id]?.raw_value ?? '').join('\n');
    const currencies = table.columns.flatMap((column) => {
      if (column.mapped_semantic_field === 'currency') {
        const cell = row.cells[column.column_id];
        // A normalized text value carries the currency code as `value`.
        const normalized = cell?.normalized_value as { value?: unknown } | null | undefined;
        return [normalized?.value ?? cell?.raw_value].filter(Boolean).map(String);
      }
      return column.header_currency ? [column.header_currency] : [];
    });
    return { ...facts, key: JSON.stringify([table.table_id, row.row_id]), text, tableName: table.name,
      included: row.classification.counts_toward_totals ?? null, currencies: [...new Set(currencies)] };
  }));
}

/** Rules compound in order. Every amount, including the percent, stays a decimal string. */
export function evaluateScenario<P extends ScenarioInput>(
  positions: readonly P[],
  rules: readonly ScenarioRule[],
  inclusion: Readonly<Record<string, boolean | null>> = {},
) {
  // Literal numbers always parse.
  let before = parseDecimal('0.00')!;
  let after = parseDecimal('0.00')!;
  let complete = positions.length > 0;
  const currencies = new Set(positions.flatMap((position) => position.currencies));
  if (currencies.size > 1 || (currencies.size > 0 && positions.some((position) => !position.currencies.length))) complete = false;
  const rows = positions.map((position) => {
    const included = inclusion[position.key] ?? position.included;
    const baseline = position.lineTotal ?? lineTotalFor(position.quantity, position.unitPrice, position.discount);
    let price = position.unitPrice;
    const applied = rules.filter((rule) => rule.keys.includes(position.key));
    for (const rule of applied) {
      const percent = parseDecimal(rule.percent);
      const current = parseDecimal(price);
      if (!percent || percent.units < -100n * 10n ** BigInt(percent.scale) || !current) {
        complete = false;
        continue;
      }
      // Literal numbers always parse.
      const factor = add(parseDecimal('1')!, multiplyDecimal(percent, parseDecimal('0.01')!));
      price = decimalToString(multiplyDecimal(current, factor));
    }
    const calculated = applied.length ? lineTotalFor(position.quantity, price, position.discount) : baseline;
    const originalCalculated = lineTotalFor(position.quantity, position.unitPrice, position.discount);
    const sourceTotal = parseDecimal(position.lineTotal);
    const original = parseDecimal(originalCalculated);
    // A hidden factor or inconsistent source amount must not silently disappear in a scenario.
    const reliable = !applied.length || (isPriced(position) && (!position.lineTotal ||
      (original && sourceTotal && subtractDecimal(sourceTotal, original).units === 0n)));
    const oldTotal = position.included === false ? '0.00' : baseline;
    const newTotal = included === false ? '0.00' : calculated;
    const oldValue = parseDecimal(oldTotal);
    const newValue = parseDecimal(newTotal);
    if (position.included === null || included === null || !oldValue || !newValue || !reliable) complete = false;
    if (oldValue) before = add(before, oldValue);
    if (newValue) after = add(after, newValue);
    return { ...position, sourceIncluded: position.included, price, oldTotal, newTotal, reliable: Boolean(reliable), included, affected: applied.length > 0 || included !== position.included,
      change: oldValue && newValue ? decimalToString(subtractDecimal(newValue, oldValue)) : null };
  });
  return { rows, complete, before: complete ? decimalToString(before) : null, after: complete ? decimalToString(after) : null,
    change: complete ? decimalToString(subtractDecimal(after, before)) : null, currency: currencies.size === 1 ? [...currencies][0] : null };
}

/** A scenario's result: each position before and after, and the bid totals when they are reliable. */
export type ScenarioResult = ReturnType<typeof evaluateScenario<ScenarioPosition>>;
