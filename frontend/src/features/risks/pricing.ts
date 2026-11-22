/**
 * The pricing view of a position: its figures from the sheet row, what the price checks of the
 * run found on it (comparable and identical positions of the same bill), whether a risk is about
 * a price, and the line total a new unit price gives. No market benchmark is invented:
 * every comparison comes from a finding of the run.
 */
import {
  compareDecimal,
  decimalToString,
  multiplyDecimal,
  parseDecimal,
  percentChange,
  roundDecimal,
  subtractDecimal,
} from '../../utils/decimal.ts';
import type { Decimal } from '../../utils/decimal.ts';
import type { Cell, CellRef, Risk, Row, TableSummary, ValidationIssue } from '../../services/apiTypes.ts';
import { findingsOf, type IssuesById } from './riskModel.ts';

/** The checks that compare a unit price with other prices: their findings speak about it. */
const PRICE_DETECTORS: ReadonlySet<string> = new Set([
  'statistical.peer_price',
  'statistical.rate_consistency',
  'statistical.open_price_reference',
  'statistical.quantity_factor',
]);

const FIELDS = ['item_code', 'description', 'quantity', 'unit', 'unit_price', 'line_total', 'discount_percent'];

const NUMBER_FIELDS = new Set(['quantity', 'unit_price', 'line_total', 'discount_percent']);

/** A number field's value only when the reader settled it as a number (never a guess from text). */
function cellValue(cell: Pick<Cell, 'raw_value' | 'normalized_value'> | undefined, field: string): string | null {
  if (!cell) return null;
  const normalized = cell.normalized_value as { kind?: string; value?: unknown } | null;
  if (normalized && normalized.kind === 'number' && normalized.value != null) return String(normalized.value);
  if (NUMBER_FIELDS.has(field)) return null;
  const raw = typeof cell.raw_value === 'string' ? cell.raw_value.trim() : null;
  return raw || null;
}

/** The figures of a position, read from its sheet row, and the columns they come from. */
export interface PriceFacts {
  rowId: string;
  tableId: string | null;
  itemCode: string | null;
  description: string | null;
  quantity: string | null;
  unit: string | null;
  unitPrice: string | null;
  lineTotal: string | null;
  discount: string | null;
  /** column id per semantic field */
  columns: Record<string, string | null>;
}

/** The figures of a sheet row, by the table's mapped columns. */
export function priceFacts(
  row: (Pick<Row, 'row_id'> & { cells?: Record<string, Pick<Cell, 'raw_value' | 'normalized_value'>> }) | null | undefined,
  table: Pick<TableSummary, 'table_id' | 'columns'> | null | undefined,
): PriceFacts | null {
  if (!row || !table) return null;
  const columns: Record<string, string | null> = {};
  const values: Record<string, string | null> = {};
  for (const field of FIELDS) {
    const column = table.columns?.find((candidate) => candidate.mapped_semantic_field === field) ?? null;
    columns[field] = column?.column_id ?? null;
    values[field] = column ? cellValue(row.cells?.[column.column_id], field) : null;
  }
  return {
    rowId: row.row_id,
    tableId: table.table_id ?? null,
    itemCode: values.item_code,
    description: values.description,
    quantity: values.quantity,
    unit: values.unit,
    unitPrice: values.unit_price,
    lineTotal: values.line_total,
    discount: values.discount_percent,
    columns,
  };
}

/** Whether the row is a priced position (a quantity and a unit price that are numbers). */
export function isPriced(facts: Pick<PriceFacts, 'quantity' | 'unitPrice'> | null | undefined): boolean {
  return Boolean(facts && parseDecimal(facts.quantity) && parseDecimal(facts.unitPrice));
}

/**
 * The line total of `quantity` at `price`: rounded to cents; with a discount in percent, the
 * discount is taken off the rounded total and the result rounded again (the GAEB rule the line
 * total check uses).
 */
export function lineTotalFor(
  quantity: string | null | undefined,
  price: string | null | undefined,
  discount: string | null = null,
): string | null {
  const q = parseDecimal(quantity);
  const p = parseDecimal(price);
  if (!q || !p) return null;
  let total = roundDecimal(multiplyDecimal(q, p), 2);
  const d = parseDecimal(discount);
  if (d && d.units !== 0n) {
    // Literal numbers always parse.
    const factor = subtractDecimal(parseDecimal('1')!, multiplyDecimal(d, parseDecimal('0.01')!));
    total = roundDecimal(multiplyDecimal(total, factor), 2);
  }
  return decimalToString(total);
}

/** `to - from` as a decimal string, or null. */
export function difference(from: string | null | undefined, to: string | null | undefined): string | null {
  const a = parseDecimal(from);
  const b = parseDecimal(to);
  return a && b ? decimalToString(subtractDecimal(b, a)) : null;
}

/** The change from `from` to `to` in percent with one decimal place, or null. */
export function percentBetween(from: string | null | undefined, to: string | null | undefined): string | null {
  const a = parseDecimal(from);
  const b = parseDecimal(to);
  return a && b ? percentChange(a, b, 1) : null;
}

type Evidence = ValidationIssue['evidence'][number];

function comparisonEvidence(issue: ValidationIssue): Evidence | null {
  return (issue.evidence ?? []).find((item) => item.kind === 'comparison' && item.data) ?? null;
}

/** What the comparable-positions check found: the spread of their unit prices. */
interface PeerComparison {
  issue: ValidationIssue;
  /** how many positions were compared, as the check reports it */
  peers: unknown;
  median: string;
  lowest: string | null;
  highest: string | null;
  label: string | null;
  detail: string | null;
}

/** What the identical-positions check found: the unit price the others have. */
interface IdenticalComparison {
  issue: ValidationIssue;
  reference: string;
  detail: string | null;
  cells: CellRef[];
  label: string | null;
}

/**
 * What the price checks found on a row, from the run's findings.
 *
 * @param issues the findings of the row
 * @returns comparable positions (`peer`), identical positions (`identical`) and the other price findings
 */
export function priceComparisons(issues: ValidationIssue[]): {
  peer: PeerComparison | null;
  identical: IdenticalComparison | null;
  others: ValidationIssue[];
} {
  let peer: PeerComparison | null = null;
  let identical: IdenticalComparison | null = null;
  const others: ValidationIssue[] = [];
  for (const issue of issues) {
    if (!PRICE_DETECTORS.has(issue.detector_id)) continue;
    const evidence = comparisonEvidence(issue);
    const data: Record<string, unknown> = evidence?.data ?? {};
    if (issue.detector_id === 'statistical.peer_price' && data.median != null && !peer) {
      peer = {
        issue,
        peers: data.peers ?? null,
        median: String(data.median),
        lowest: data.lowest != null ? String(data.lowest) : null,
        highest: data.highest != null ? String(data.highest) : null,
        label: evidence!.label ?? null,
        detail: evidence!.detail ?? null,
      };
    } else if (issue.detector_id === 'statistical.rate_consistency' && data.reference != null && !identical) {
      identical = {
        issue,
        reference: String(data.reference),
        detail: evidence!.detail ?? null,
        cells: evidence!.cells ?? [],
        label: evidence!.label ?? null,
      };
    } else {
      others.push(issue);
    }
  }
  return { peer, identical, others };
}

/** Findings that touch a row (their row or one of their cells). */
export function findingsOnRow(issues: ValidationIssue[], rowId: string | null | undefined): ValidationIssue[] {
  if (!rowId) return [];
  return issues.filter(
    (issue) => issue.row_id === rowId || (issue.affected_cells ?? []).some((cell) => cell.row_id === rowId),
  );
}

/**
 * Whether a risk is about a price: it has a comparison amount, an exact or estimated amount in
 * the pricing or quantity categories, or a finding of a price check. Its detail then opens the
 * price of its position.
 */
export function isPriceRisk(
  risk: Pick<Risk, 'money' | 'category' | 'source_issue_ids'> | null | undefined,
  issuesById: IssuesById | null | undefined,
): boolean {
  if (!risk) return false;
  const money = risk.money;
  if (money?.reference) return true;
  if ((money?.kind === 'exact' || money.kind === 'estimate') && ['pricing', 'quantity'].includes(risk.category)) return true;
  return findingsOf(risk, issuesById).some((issue) => PRICE_DETECTORS.has(issue.detector_id));
}

/**
 * Positions of a range bar between 0 and the largest value (0 to 1), or null when a value is
 * missing. A plain linear scale from zero, so the distances read true.
 */
export function rangePositions(
  values: Record<string, string | null | undefined>,
): Record<string, number | null> | null {
  const parsed = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, parseDecimal(value)]));
  const present = Object.values(parsed).filter((value): value is Decimal => value !== null);
  if (!present.length) return null;
  const max = present.reduce((largest, value) => (compareDecimal(value, largest) > 0 ? value : largest));
  if (max.units <= 0n) return null;
  const share = (value: Decimal | null) => {
    if (!value) return null;
    // value / max on scaled integers with four digits, then a number between 0 and 1.
    const scale = Math.max(value.scale, max.scale);
    const v = value.units * 10n ** BigInt(scale - value.scale);
    const m = max.units * 10n ** BigInt(scale - max.scale);
    return Math.max(0, Number((v * 10000n) / m) / 10000);
  };
  return Object.fromEntries(Object.entries(parsed).map(([key, value]) => [key, share(value)]));
}
