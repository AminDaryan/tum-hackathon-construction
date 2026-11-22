/**
 * Where a finding points in the sheet: the first affected cell, else the first input cell, else
 * its row; `null` for a finding about the whole table.
 */
import type { CellRef } from '../../services/apiTypes.ts';

/** A place in the sheet: a cell, or a row when `columnId` is null. */
export interface SheetTarget {
  tableId: string;
  rowId: string;
  columnId: string | null;
}

export function issueTarget(
  issue: {
    affected_cells?: CellRef[];
    input_cells?: CellRef[];
    row_id?: string | null;
    table_id?: string | null;
  } | null | undefined,
): SheetTarget | null {
  if (!issue) return null;
  const cells = issue.affected_cells?.length ? issue.affected_cells : (issue.input_cells ?? []);
  const cell = cells.find((candidate) => candidate.row_id);
  if (cell) return { tableId: cell.table_id, rowId: cell.row_id, columnId: cell.column_id ?? null };
  if (issue.row_id && issue.table_id) return { tableId: issue.table_id, rowId: issue.row_id, columnId: null };
  return null;
}
