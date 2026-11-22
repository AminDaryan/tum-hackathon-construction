/**
 * Pure helpers of the sheet: where the active cell goes for a key, which key starts editing,
 * and how a cell is named (its A1 address in the source file).
 */
import { t } from '../../../i18n/messages.ts';
import { a1Reference } from '../../../utils/a1.ts';

/** Rows per page of the sheet. */
export const SHEET_PAGE_SIZE = 100;

/** Rows that Page Up and Page Down move. */
export const PAGE_STEP = 10;

/**
 * The cell the active cell moves to for `key`, or null when the key does not move it. Arrow
 * keys move one cell and stop at the edges; Home and End go to the first and last cell of the
 * row (with Ctrl or Cmd: of the page); Page Up and Page Down move {@link PAGE_STEP} rows.
 *
 * @param position 0-based indices on the page
 * @param key KeyboardEvent.key
 */
export function moveCell(
  position: { row: number; column: number } | null,
  key: string,
  { rowCount, columnCount, ctrlKey = false }: { rowCount: number; columnCount: number; ctrlKey?: boolean },
): { row: number, column: number } | null {
  if (!position || rowCount < 1 || columnCount < 1) {
    return null;
  }
  const lastRow = rowCount - 1;
  const lastColumn = columnCount - 1;
  const row = Math.min(Math.max(position.row, 0), lastRow);
  const column = Math.min(Math.max(position.column, 0), lastColumn);
  switch (key) {
    case 'ArrowUp':
      return { row: Math.max(0, row - 1), column };
    case 'ArrowDown':
      return { row: Math.min(lastRow, row + 1), column };
    case 'ArrowLeft':
      return { row, column: Math.max(0, column - 1) };
    case 'ArrowRight':
      return { row, column: Math.min(lastColumn, column + 1) };
    case 'Home':
      return ctrlKey ? { row: 0, column: 0 } : { row, column: 0 };
    case 'End':
      return ctrlKey ? { row: lastRow, column: lastColumn } : { row, column: lastColumn };
    case 'PageUp':
      return { row: Math.max(0, row - PAGE_STEP), column };
    case 'PageDown':
      return { row: Math.min(lastRow, row + PAGE_STEP), column };
    default:
      return null;
  }
}

/**
 * The cell after `position` in the direction an editor's Tab (`right`) or Shift+Tab (`left`)
 * leaves it, staying on the same row.
 */
export function stepAcross(
  position: { row: number; column: number },
  direction: 'left' | 'right',
  columnCount: number,
): { row: number, column: number } {
  const column = direction === 'left' ? position.column - 1 : position.column + 1;
  return { row: position.row, column: Math.min(Math.max(column, 0), Math.max(columnCount - 1, 0)) };
}

/**
 * Whether a key starts editing the active cell with the cell's text (Enter, F2).
 */
export function isEditKey(event: { key: string, ctrlKey?: boolean, metaKey?: boolean, altKey?: boolean }) {
  return (event.key === 'Enter' || event.key === 'F2') && !event.ctrlKey && !event.metaKey && !event.altKey;
}

/**
 * The character a key types, when it starts editing with that character, else null.
 */
export function printableKey(
  event: { key: string; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean; isComposing?: boolean },
): string | null {
  if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) {
    return null;
  }
  return typeof event.key === 'string' && [...event.key].length === 1 ? event.key : null;
}

/**
 * The cell's address in the source file, such as `D14`: the source row number and the source
 * column letter. Falls back to the cell's own A1 reference, then to the column header and row.
 */
export function cellAddress(
  row: { source_row_number?: number | null },
  column: { source_column_number?: number | null; original_header?: string | null; normalized_name?: string },
  cell?: { source?: { a1?: string | null } | null } | null,
): string {
  return (
    a1Reference(row.source_row_number, column.source_column_number) ??
    cell?.source?.a1 ??
    t('{column}, row {row}', { column: column.original_header || column.normalized_name || t('Column'), row: row.source_row_number ?? '?' })
  );
}

/**
 * A key for one cell of one table page, usable in maps and sets.
 */
export function cellKey(rowId: string, columnId: string) {
  return `${rowId}\u0000${columnId}`;
}

/**
 * Columns in sheet order (by their position in the table).
 */
export function sortColumns<T extends { position: number }>(columns: T[]): T[] {
  return [...columns].sort((a, b) => a.position - b.position);
}
