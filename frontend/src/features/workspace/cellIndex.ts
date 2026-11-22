import type { ValidationIssue } from '../../services/apiTypes.ts';
import { compareFindings } from '../issues/runFindings.ts';

const EMPTY: readonly ValidationIssue[] = Object.freeze([]);
const key = (...parts: string[]) => parts.join('\u0000');

/** Where the findings of a run are in the sheet (see {@link cellIndex}). */
export interface CellIndex {
  size: number;
  forRow: (tableId: string, rowId: string) => readonly ValidationIssue[];
  forCell: (tableId: string, rowId: string, columnId: string) => readonly ValidationIssue[];
}

/**
 * Where the findings of a run are in the sheet: every finding of a row (`forRow`) and every
 * finding that marks a cell (`forCell`, its affected cells), strongest first, in all review
 * states (the sheet decides which still mark a cell).
 */
export function cellIndex(issues: ValidationIssue[]): CellIndex {
  const rows = new Map<string, ValidationIssue[]>();
  const cells = new Map<string, ValidationIssue[]>();
  const add = (map: Map<string, ValidationIssue[]>, k: string, issue: ValidationIssue) => {
    const list = map.get(k) ?? [];
    if (!list.includes(issue)) list.push(issue);
    map.set(k, list);
  };
  for (const issue of issues) {
    if (issue.table_id && issue.row_id) add(rows, key(issue.table_id, issue.row_id), issue);
    for (const cell of issue.affected_cells ?? []) {
      if (!cell.table_id || !cell.row_id) continue;
      add(rows, key(cell.table_id, cell.row_id), issue);
      if (cell.column_id) add(cells, key(cell.table_id, cell.row_id, cell.column_id), issue);
    }
  }
  for (const list of [...rows.values(), ...cells.values()]) list.sort(compareFindings);
  return {
    size: issues.length,
    forRow: (tableId, rowId) => rows.get(key(tableId, rowId)) ?? EMPTY,
    forCell: (tableId, rowId, columnId) => cells.get(key(tableId, rowId, columnId)) ?? EMPTY,
  };
}
