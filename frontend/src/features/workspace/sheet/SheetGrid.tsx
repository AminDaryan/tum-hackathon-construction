import { useLayoutEffect, type KeyboardEvent, type RefObject, type SyntheticEvent } from 'react';
import { getLocale, t } from '../../../i18n/messages.ts';
import { columnLetter } from '../../../utils/a1.ts';
import { cx } from '../../../utils/classNames.ts';
import { humanize, labelFor, ROW_KIND_LABELS } from '../../../utils/vocabulary.ts';
import type { CellIndex } from '../cellIndex.ts';
import { CellEditor, type CellEditorProps } from './CellEditor.tsx';
import { SheetCell } from './SheetCell.tsx';
import { FROZEN_COLUMN } from './sheetLayout.ts';
import { openCellCount, rowHasOpenFindings } from './sheetFindings.ts';
import { cellKey, isEditKey, moveCell, printableKey } from './sheetMoves.ts';
import type { Column, Row } from '../../../services/apiTypes.ts';

const TOTAL_KINDS = new Set(['subtotal', 'grand_total', 'tax', 'gross_total']);

// Two sticky header rows: column letters (24 px) and the file's headers (32 px) under them.
const LETTER_CELL = 'sticky top-0 z-[4] h-6 border-b border-r border-hairline bg-sidebar px-2 text-center text-caption font-normal text-ink-tertiary';
const HEADER_CELL = 'sticky top-6 z-[4] h-8 border-b border-r border-hairline-strong bg-surface px-2 text-left text-caption font-semibold text-ink';
const CORNER = 'left-0 z-[5] w-12 min-w-12';

function rowClass(row: Row) {
  const kind = row.classification.kind;
  return cx(
    (kind === 'section' || TOTAL_KINDS.has(kind)) && 'font-semibold',
    row.excluded ? 'text-ink-tertiary' : 'text-ink',
  );
}

function rowTitle(row: Row) {
  const kind = t(labelFor(ROW_KIND_LABELS, row.classification.kind));
  return row.excluded ? t('{kind}, excluded from the checks', { kind }) : kind;
}

/** A column's field in the header's tooltip: lower case in English, a noun as written in German. */
function fieldName(field: string) {
  const name = t(humanize(field));
  return getLocale() === 'de' ? name : name.toLowerCase();
}

/** Whether an event comes from the cell editor's text field, which handles its own keys. */
function fromEditor(event: SyntheticEvent) {
  return event.target instanceof Element && event.target.closest('textarea') !== null;
}

function eventCell(event: SyntheticEvent<HTMLTableElement>): GridPosition | null {
  const cell = event.target instanceof Element ? event.target.closest<HTMLElement>('td[data-column-index]') : null;
  if (!cell || !event.currentTarget.contains(cell)) return null;
  return { row: Number(cell.dataset.rowIndex), column: Number(cell.dataset.columnIndex) };
}

interface SheetGridProps {
  label: string;
  tableId: string;
  columns: Column[];
  rows: Row[];
  offset: number;
  total: number;
  active?: GridPosition | null;
  editing?: GridEditing | null;
  pending: Record<string, string>;
  flashKey?: string | null;
  findingsIndex: CellIndex;
  selectedKeys: ReadonlySet<string>;
  tableRef: RefObject<HTMLTableElement | null>;
  /** Freeze the description beside the item numbers too (a wide enough sheet). */
  freezeDescription?: boolean;
  onActivate: (at: GridPosition) => void;
  onMove: (at: GridPosition) => void;
  onStartEdit: (at: GridPosition, character: string | null) => void;
  onCommitEdit: CellEditorProps['onCommit'];
  onCancelEdit: () => void;
  onEscape: () => void;
}

/**
 * The sheet's table: an ARIA grid with sticky column letters, the file's column headers and a
 * sticky column of source row numbers. A row with open findings shows its number in Red pen.
 *
 * Keyboard (ARIA grid pattern): only the active cell is in the Tab order; arrow keys, Home,
 * End (with Ctrl or Cmd: first and last cell of the page), Page Up and Page Down move it;
 * Enter or F2 edits it; typing a character edits it starting with that character; Escape
 * closes the cell note. Click selects a cell, double-click edits it.
 */
export function SheetGrid({
  label,
  tableId,
  columns,
  rows,
  offset,
  total,
  active,
  editing,
  pending,
  flashKey,
  findingsIndex,
  selectedKeys,
  tableRef,
  freezeDescription = true,
  onActivate,
  onMove,
  onStartEdit,
  onCommitEdit,
  onCancelEdit,
  onEscape,
}: SheetGridProps) {
  // Parse markers are buttons inside cells. They keep their hover note, but leave the Tab order
  // so that Tab leaves the grid; their note is in the cell bar for the active cell.
  useLayoutEffect(() => {
    for (const button of tableRef.current?.querySelectorAll<HTMLElement>('tbody button') ?? []) {
      button.tabIndex = -1;
    }
  });

  const handleKeyDown = (event: KeyboardEvent<HTMLTableElement>) => {
    if (fromEditor(event) || !active) return;
    if (event.key === 'Escape') {
      onEscape();
      return;
    }
    if (isEditKey(event)) {
      event.preventDefault();
      onStartEdit(active, null);
      return;
    }
    const next = moveCell(active, event.key, {
      rowCount: rows.length,
      columnCount: columns.length,
      ctrlKey: event.ctrlKey || event.metaKey,
    });
    if (next) {
      event.preventDefault();
      onMove(next);
      return;
    }
    const character = printableKey(event);
    if (character !== null) {
      event.preventDefault();
      onStartEdit(active, character);
    }
  };

  const handleFocus = (event: SyntheticEvent<HTMLTableElement>) => {
    if (fromEditor(event)) return;
    const target = eventCell(event);
    if (target) onActivate(target);
  };

  const handleDoubleClick = (event: SyntheticEvent<HTMLTableElement>) => {
    if (fromEditor(event)) return;
    const target = eventCell(event);
    if (target) onStartEdit(target, null);
  };

  const tabStop = active ?? { row: 0, column: 0 };
  // The item numbers, and a narrow description beside them, stay in view next to the row
  // numbers, so a jump to a far column (the amount) still shows which position it is.
  const frozenItem = columns[0]?.mapped_semantic_field === 'item_code';
  const frozenDescription = freezeDescription && frozenItem && columns[1]?.mapped_semantic_field === 'description';
  const frozenAt = (columnIndex: number) =>
    frozenItem && columnIndex === 0 ? 'item' : frozenDescription && columnIndex === 1 ? 'description' : undefined;
  const frozenHeader = (columnIndex: number) => {
    const frozen = frozenAt(columnIndex);
    return frozen && cx('z-[5]', FROZEN_COLUMN[frozen]);
  };

  return (
    <table
      ref={tableRef}
      role="grid"
      aria-label={label}
      aria-rowcount={total + 2}
      aria-colcount={columns.length + 1}
      onKeyDown={handleKeyDown}
      onFocus={handleFocus}
      onDoubleClick={handleDoubleClick}
      className="w-max min-w-full border-separate border-spacing-0 bg-surface"
    >
      <thead>
        <tr aria-rowindex={1}>
          <th scope="col" className={cx(LETTER_CELL, CORNER)} />
          {columns.map((column, columnIndex) => (
            <th key={column.column_id} scope="col" className={cx(LETTER_CELL, frozenHeader(columnIndex))}>
              {columnLetter(column.source_column_number)}
            </th>
          ))}
        </tr>
        <tr aria-rowindex={2}>
          <th scope="col" className={cx(HEADER_CELL, CORNER, 'bg-sidebar text-right')}>
            <span className="sr-only">{t('Row')}</span>
          </th>
          {columns.map((column, columnIndex) => {
            const header = column.original_header || column.normalized_name;
            const field = column.mapped_semantic_field;
            return (
              <th
                key={column.column_id}
                scope="col"
                title={field ? t('Read as {field}', { field: fieldName(field) }) : t('Not linked to a field')}
                className={cx(HEADER_CELL, column.inferred_type === 'number' && 'text-right', frozenHeader(columnIndex))}
              >
                <div className={cx('truncate', frozenAt(columnIndex) ? 'min-w-0' : 'min-w-[72px] max-w-[320px]')}>{header}</div>
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rowIndex) => {
          const rowOpen = rowHasOpenFindings(findingsIndex, tableId, row.row_id);
          const tone = row.classification.kind === 'section' ? 'section' : 'plain';
          return (
            <tr key={row.row_id} aria-rowindex={offset + rowIndex + 3} className={rowClass(row)}>
              <th
                scope="row"
                title={rowTitle(row)}
                className={cx(
                  'sticky left-0 z-[2] h-8 w-12 min-w-12 border-b border-r border-hairline bg-sidebar px-2 text-right text-caption sheet-figures',
                  rowOpen ? 'font-semibold text-violation' : 'font-normal text-ink-secondary',
                )}
              >
                <span className="inline-flex items-center justify-end gap-1">
                  {rowOpen && <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-violation" />}
                  {row.source_row_number}
                  {rowOpen && <span className="sr-only">{t(', has open findings')}</span>}
                </span>
              </th>
              {columns.map((column, columnIndex) => {
                const key = cellKey(row.row_id, column.column_id);
                const isActive = active?.row === rowIndex && active.column === columnIndex;
                const isEditing = editing?.row === rowIndex && editing.column === columnIndex;
                return (
                  <SheetCell
                    key={column.column_id}
                    cell={row.cells[column.column_id] ?? null}
                    rowIndex={rowIndex}
                    columnIndex={columnIndex}
                    tabbable={tabStop.row === rowIndex && tabStop.column === columnIndex}
                    active={isActive}
                    openFindings={openCellCount(findingsIndex, tableId, row.row_id, column.column_id)}
                    inSelectedIssue={selectedKeys.has(key)}
                    flashing={flashKey === key}
                    pendingText={pending[key] ?? null}
                    tone={tone}
                    frozen={frozenAt(columnIndex)}
                  >
                    {isEditing && (
                      <CellEditor
                        label={editing.label}
                        initialText={editing.initialText}
                        selectAll={editing.selectAll}
                        onCommit={onCommitEdit}
                        onCancel={onCancelEdit}
                      />
                    )}
                  </SheetCell>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** A cell by its place on the page. */
export interface GridPosition {
  row: number;
  column: number;
}

/** The cell being edited and how its editor opens. */
export interface GridEditing extends GridPosition {
  label: string;
  initialText: string;
  selectAll: boolean;
}
