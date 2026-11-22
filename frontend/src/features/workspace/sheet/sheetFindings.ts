/**
 * Where the findings of a run mark the sheet: open findings wash their cells red, the selected
 * issue rings its cells, and the cell note lists the findings of one cell.
 */
import type { CellRef, ValidationIssue } from '../../../services/apiTypes.ts';
import { compareFindings } from '../../issues/runFindings.ts';
import { cellIndex, type CellIndex } from '../cellIndex.ts';
import { isOpenFinding } from '../reviewLabels.ts';
import { cellKey } from './sheetMoves.ts';

/** Findings the cell note lists before it points to the Risks tab. */
export const NOTE_LIMIT = 3;

const NONE: readonly never[] = Object.freeze([]);

/** An index without findings (before the first validation), shaped like {@link cellIndex}. */
export const NO_CELL_FINDINGS = cellIndex([]);

/**
 * The findings (all review states, strongest first) whose affected cells include one cell.
 */
export function cellFindings(
  index: Pick<CellIndex, 'forCell'>,
  tableId: string,
  rowId: string,
  columnId: string,
): readonly ValidationIssue[] {
  return index.forCell(tableId, rowId, columnId) ?? NONE;
}

/**
 * How many open findings mark a cell (they wash it red).
 */
export function openCellCount(
  index: Pick<CellIndex, 'forCell'>,
  tableId: string,
  rowId: string,
  columnId: string,
): number {
  return cellFindings(index, tableId, rowId, columnId).filter(isOpenFinding).length;
}

/**
 * Whether a row has open findings (its number is shown in Red pen).
 */
export function rowHasOpenFindings(index: Pick<CellIndex, 'forRow'>, tableId: string, rowId: string): boolean {
  return (index.forRow(tableId, rowId) ?? NONE).some(isOpenFinding);
}

/**
 * Keys ({@link cellKey}) of the cells of `tableId` that the issue names as affected.
 */
export function issueCellKeys(issue: { affected_cells?: CellRef[] } | null | undefined, tableId: string): Set<string> {
  const keys = new Set<string>();
  for (const cell of issue?.affected_cells ?? NONE) {
    if (cell.table_id === tableId && cell.row_id && cell.column_id) keys.add(cellKey(cell.row_id, cell.column_id));
  }
  return keys;
}

/**
 * Whether the issue is about a row: its own row, or a row of one of its cells.
 */
export function issueTouchesRow(
  issue: { table_id?: string | null; row_id?: string | null; affected_cells?: CellRef[]; input_cells?: CellRef[] },
  tableId: string,
  rowId: string,
): boolean {
  if (issue.row_id === rowId && (!issue.table_id || issue.table_id === tableId)) return true;
  return [...(issue.affected_cells ?? NONE), ...(issue.input_cells ?? NONE)].some(
    (cell) => cell.table_id === tableId && cell.row_id === rowId,
  );
}

/**
 * The findings the cell note lists: the open findings of the cell and, for a cell that was
 * revealed for the selected issue, that issue too. The selected issue comes first, then the
 * others by {@link compareFindings}.
 *
 * @param findings the cell's findings (all review states)
 * @param includeSelected whether the selected issue belongs in the note anyway
 */
export function noteFindings(
  findings: readonly ValidationIssue[],
  selectedIssue: ValidationIssue | null | undefined,
  includeSelected: boolean,
): ValidationIssue[] {
  const open = findings.filter(isOpenFinding);
  const selectedId = selectedIssue?.issue_id ?? null;
  const listed = open.some((issue) => issue.issue_id === selectedId);
  const issues = includeSelected && selectedIssue && !listed ? [selectedIssue, ...open] : open;
  return [...issues].sort(
    (a, b) => Number(b.issue_id === selectedId) - Number(a.issue_id === selectedId) || compareFindings(a, b),
  );
}
