import { FileText, Maximize2, Minimize2, Rows3, Table2 } from 'lucide-react';
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ToggleButton } from 'react-aria-components';
import { Button } from '../../../components/Button.tsx';
import { HIT_MIN_HEIGHT } from '../../../components/hitTarget.ts';
import { IconButton } from '../../../components/IconButton.tsx';
import { EmptyState } from '../../../components/EmptyState.tsx';
import { ErrorState } from '../../../components/ErrorState.tsx';
import { LoadingState } from '../../../components/LoadingState.tsx';
import { Pagination } from '../../../components/Pagination.tsx';
import { Select } from '../../../components/Select.tsx';
import { msg, t } from '../../../i18n/messages.ts';
import { cx } from '../../../utils/classNames.ts';
import type { CellIndex } from '../cellIndex.ts';
import { rawText, readingNote } from './cellText.ts';
import { SheetGrid, type GridEditing, type GridPosition } from './SheetGrid.tsx';
import { SheetNote } from './SheetNote.tsx';
import { SheetPdf, type PdfSource } from './SheetPdf.tsx';
import { SHEET_FOOTER, SHEET_SCROLLER, SHEET_SCROLLER_FILL, ARITHMETIC_FIELDS, FREEZE_DESCRIPTION_MIN_WIDTH } from './sheetLayout.ts';
import { cellAt, prefersReducedMotion, scrollCellIntoView } from './sheetDom.ts';
import { cellFindings, issueCellKeys, issueTouchesRow, NO_CELL_FINDINGS, noteFindings } from './sheetFindings.ts';
import { cellAddress, cellKey, SHEET_PAGE_SIZE, sortColumns, stepAcross } from './sheetMoves.ts';
import { useCellSaves, type SaveOutcome } from './useCellSaves.ts';
import { useSheetRows } from './useSheetRows.ts';
import type { ReactNode } from 'react';
import type { CorrectionsResult, Row, TableSummary, ValidationIssue } from '../../../services/apiTypes.ts';

/** How long the ring of a cell that was jumped to flashes. */
const FLASH_MS = 600;

/** A cell to go to; a new `nonce` asks again for the same cell. */
export interface Reveal {
  tableId?: string | null;
  rowId?: string;
  /** without one, the row's first cell */
  columnId?: string | null;
  /** Open the cell's editor once it is shown (Approve on a risk). */
  edit?: boolean;
  nonce: number | string;
}

/** A cell by its row and column id. */
interface CellTarget {
  rowId: string;
  columnId: string;
}

type View = 'table' | 'pdf';

function sameCell(a: CellTarget | null, b: CellTarget | null) {
  return a !== null && b !== null && a.rowId === b.rowId && a.columnId === b.columnId;
}

function useLatest<T>(value: T) {
  const ref = useRef(value);
  useLayoutEffect(() => {
    ref.current = value;
  });
  return ref;
}

const VIEWS = [
  { value: 'table', label: msg('Table'), icon: Table2 },
  { value: 'pdf', label: msg('PDF'), icon: FileText },
] as const;

interface ViewSwitchProps {
  view: View;
  onChange: (view: View) => void;
}

/**
 * Table or PDF, as a segmented control. The visible segment is 32 px tall so the cell bar keeps
 * its height; each button's hit area reaches 44 px (48 for a finger) into the bar's padding.
 */
function ViewSwitch({ view, onChange }: ViewSwitchProps) {
  return (
    <div role="group" aria-label={t('View')} className="flex h-8 shrink-0 items-center self-center rounded-md bg-sidebar p-0.5">
      {VIEWS.map(({ value, label, icon: Icon }) => {
        const active = view === value;
        return (
          <ToggleButton
            key={value}
            isSelected={active}
            onChange={() => onChange(value)}
            className={cx('group -my-1.5 flex cursor-pointer items-center outline-none pointer-coarse:-my-2', HIT_MIN_HEIGHT)}
          >
            <span
              className={cx(
                'inline-flex h-7 items-center gap-1.5 rounded-sm px-3 text-callout transition-colors group-data-focus-visible:outline-2 group-data-focus-visible:outline-focus',
                active ? 'bg-surface font-medium text-ink shadow-sm' : 'text-ink-secondary group-hover:text-ink',
              )}
            >
              <Icon aria-hidden="true" className="size-4" strokeWidth={1.75} />
              {t(label)}
            </span>
          </ToggleButton>
        );
      })}
    </div>
  );
}

interface CellBarProps {
  reference?: string | null;
  text?: string | null;
  note?: string | null;
  trailing?: ReactNode;
}

/**
 * The active cell's address, its full text and how the app read it; the view switch on the right.
 * With no cell active the bar keeps its height and is empty but for the switch.
 */
function CellBar({ reference, text, note, trailing = null }: CellBarProps) {
  return (
    <div role="group" aria-label={t('Active cell')} className="flex min-h-10 items-start gap-3 border-b border-hairline px-4 py-1.5">
      {reference && (
        <>
          <span className="inline-flex h-7 min-w-12 shrink-0 items-center justify-center rounded-sm bg-sidebar px-2 text-caption font-semibold text-ink sheet-figures">
            {reference}
          </span>
          <p
            className={cx(
              'max-h-9 min-w-0 flex-1 self-center overflow-y-auto whitespace-pre-wrap break-words text-callout sheet-figures',
              text ? 'text-ink' : 'text-ink-tertiary',
            )}
          >
            {text || t('Empty cell')}
          </p>
          {note && <p className="max-w-[40%] shrink-0 self-center text-caption text-ink-secondary">{note}</p>}
        </>
      )}
      {trailing && <div className="ml-auto flex shrink-0 self-center">{trailing}</div>}
    </div>
  );
}

interface SaveStatusProps {
  status: SaveOutcome | null;
  onUndo: () => void;
  onReloadTable: () => void;
}

/** The footer's save line: progress and results in a status region, failures as an alert. */
function SaveStatus({ status, onUndo, onReloadTable }: SaveStatusProps) {
  let message = '';
  if (status?.kind === 'saving') {
    message = t('Saving {reference}…', { reference: status.reference });
  } else if (status?.kind === 'saved') {
    message = t('Saved {reference} as revision {revision}.', { reference: status.reference, revision: status.revision });
    if (status.caveat) message = `${message} ${t('The uploaded file is not changed.')}`;
  } else if (status?.kind === 'restored') {
    message = t('Restored the previous text of {reference} as revision {revision}.', { reference: status.reference, revision: status.revision });
  } else if (status?.kind === 'unchanged') {
    message = t('{reference} already holds this text. Nothing was saved.', { reference: status.reference });
  }
  let alert = null;
  if (status?.kind === 'conflict') {
    alert = status.currentRevision
      ? t('This table was changed somewhere else and is now at revision {revision}. Reload the table to continue.', { revision: status.currentRevision })
      : t('This table was changed somewhere else. Reload the table to continue.');
  } else if (status?.kind === 'error') {
    alert = t('{reference} was not saved. {message}', { reference: status.reference, message: status.message });
  }
  return (
    <div className="flex min-w-0 flex-1 flex-col justify-center px-4 py-1">
      <div className="flex flex-wrap items-center gap-x-2">
        <p role="status" className="text-callout text-ink-secondary">
          {message}
        </p>
        {status?.kind === 'saved' && (
          <Button variant="ghost" onPress={onUndo}>
            {t('Undo')}
          </Button>
        )}
      </div>
      {alert && (
        <div role="alert" className="flex flex-wrap items-center gap-x-3 text-callout text-danger">
          <p>{alert}</p>
          {status?.kind === 'conflict' && <Button onPress={onReloadTable}>{t('Reload table')}</Button>}
        </div>
      )}
    </div>
  );
}

interface SheetBodyProps {
  datasetId: string;
  table: TableSummary;
  revision: number;
  onRevised?: (result: CorrectionsResult) => void;
  onReload?: () => void;
  findingsIndex: CellIndex;
  selectedIssue?: ValidationIssue | null;
  reveal?: Reveal | null;
  onReview?: (issue: ValidationIssue) => void;
  showNotes: boolean;
  onCellFindings?: (found: readonly ValidationIssue[]) => void;
  onRowsLoaded?: (rows: Row[]) => void;
  pdf?: PdfSource | null;
  view: View;
  onViewChange: (view: View) => void;
  fill?: boolean;
}

/**
 * Cell bar, grid, cell note and footer of one table. Keyed by dataset and table in
 * {@link Sheet}, so switching tables starts with a fresh page, cursor and save line.
 */
function SheetBody({
  datasetId,
  table,
  revision,
  onRevised,
  onReload,
  findingsIndex,
  selectedIssue,
  reveal,
  onReview,
  showNotes,
  onCellFindings,
  onRowsLoaded,
  pdf,
  view,
  onViewChange,
  fill = false,
}: SheetBodyProps) {
  const tableId = table.table_id;
  const columns = useMemo(() => sortColumns(table.columns), [table.columns]);
  const revealHere = reveal?.rowId && (!reveal.tableId || reveal.tableId === tableId) ? reveal : null;
  const sheet = useSheetRows({ datasetId, tableId, initialRowId: revealHere?.rowId ?? null });
  const { rows, applyRows, showRow } = sheet;
  const total = sheet.total ?? table.row_count;

  const containerRef = useRef<HTMLDivElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  // A narrow sheet (a small window beside the side panel) freezes only the item numbers.
  const [scrollerWidth, setScrollerWidth] = useState(Infinity);
  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => setScrollerWidth(scroller.clientWidth));
    observer.observe(scroller);
    return () => observer.disconnect();
  });
  const tableRef = useRef<HTMLTableElement>(null);
  const flashTimer = useRef<number | undefined>(undefined);
  const [active, setActive] = useState<CellTarget | null>(null);
  const [editing, setEditing] = useState<(CellTarget & Omit<GridEditing, 'row' | 'column'>) | null>(null);
  const [dismissedKey, setDismissedKey] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<CellTarget | null>(null);
  const [focusRequest, setFocusRequest] = useState<(CellTarget & { center?: boolean; focus: boolean; flash?: boolean }) | null>(null);
  const [flashKey, setFlashKey] = useState<string | null>(null);
  const [seenNonce, setSeenNonce] = useState<Reveal['nonce'] | null>(null);
  const [pendingReveal, setPendingReveal] = useState<Reveal | null>(null);

  // A new reveal (new nonce) for this table: remember it until its row is on the page.
  if (revealHere && revealHere.nonce !== seenNonce) {
    setSeenNonce(revealHere.nonce);
    setPendingReveal(revealHere);
  }

  const onRevisedRef = useLatest(onRevised);
  const onRowsLoadedRef = useLatest(onRowsLoaded);
  const onCellFindingsRef = useLatest(onCellFindings);
  const handleSaved = useCallback(
    (result: CorrectionsResult) => {
      applyRows(result.rows ?? []);
      onRevisedRef.current?.(result);
    },
    [applyRows, onRevisedRef],
  );
  const saves = useCellSaves({ datasetId, tableId, revision, onSaved: handleSaved });
  const { pending } = saves;

  const position = useMemo(() => {
    if (!active || !rows) return null;
    const row = rows.findIndex((candidate) => candidate.row_id === active.rowId);
    const column = columns.findIndex((candidate) => candidate.column_id === active.columnId);
    return row >= 0 && column >= 0 ? { row, column } : null;
  }, [active, rows, columns]);
  // A position is only found while rows are on hand.
  const activeRow = position ? rows![position.row] : null;
  const activeColumn = position ? columns[position.column] : null;
  const activeCell = activeRow && activeColumn ? (activeRow.cells[activeColumn.column_id] ?? null) : null;
  const activeKey = active ? cellKey(active.rowId, active.columnId) : null;
  const activeReference = activeRow && activeColumn ? cellAddress(activeRow, activeColumn, activeCell) : null;
  const ozColumnId = useMemo(
    () => columns.find((column) => column.mapped_semantic_field === 'item_code')?.column_id ?? null,
    [columns],
  );
  const pdfTarget = useMemo(() => {
    if (!activeRow || !activeColumn) return null;
    const oz = ozColumnId ? activeRow.cells[ozColumnId]?.raw_value : null;
    return {
      oz: typeof oz === 'string' && oz.trim() ? oz.trim() : null,
      cell: activeCell,
      isOz: activeColumn.column_id === ozColumnId,
      reference: activeReference,
      column: activeColumn.original_header || activeColumn.normalized_name || null,
    };
  }, [activeRow, activeColumn, activeCell, activeReference, ozColumnId]);
  const showPdf = Boolean(pdf) && view === 'pdf';

  // Only the grid, which is shown with rows, asks for a target.
  const targetAt = (at: GridPosition): CellTarget => ({ rowId: rows![at.row].row_id, columnId: columns[at.column].column_id });
  const activate = (target: CellTarget) => {
    if (sameCell(active, target)) return;
    setActive(target);
    setDismissedKey(null);
  };
  // The reviewer went to another cell (click, Tab or the arrow keys): its findings, if any.
  const activateByUser = (target: CellTarget) => {
    if (sameCell(active, target)) return;
    activate(target);
    const found = cellFindings(findingsIndex, tableId, target.rowId, target.columnId);
    if (found.length) onCellFindingsRef.current?.(found);
  };

  useEffect(() => {
    if (rows) onRowsLoadedRef.current?.(rows);
  }, [rows, onRowsLoadedRef]);

  // Go to the revealed cell: use the page on hand when it holds the row, else ask the server
  // for the page that does. Then make the cell active, centre it, open its note and flash it.
  useEffect(() => {
    if (!pendingReveal) return;
    if (sheet.error) {
      setPendingReveal(null);
      return;
    }
    const rowIndex = rows ? rows.findIndex((row) => row.row_id === pendingReveal.rowId) : -1;
    if (rows && rowIndex >= 0) {
      const column = columns.find((candidate) => candidate.column_id === pendingReveal.columnId) ?? columns[0];
      setPendingReveal(null);
      if (!column) return;
      const columnId = column.column_id;
      const target = { rowId: rows[rowIndex].row_id, columnId };
      setActive(target);
      setDismissedKey(null);
      setRevealed(target);
      if (pendingReveal.edit && pending[cellKey(target.rowId, columnId)] === undefined) {
        // Approve on a risk: the cell opens for editing with its value selected.
        const row = rows[rowIndex];
        const cell = row.cells[columnId] ?? null;
        setEditing({ ...target, label: t('Edit {cell}', { cell: cellAddress(row, column, cell) }), initialText: rawText(cell), selectAll: true });
        setFocusRequest({ ...target, center: true, focus: false, flash: true });
        return;
      }
      const focusInside = Boolean(containerRef.current?.contains(document.activeElement));
      setFocusRequest({ ...target, center: true, focus: focusInside, flash: true });
      return;
    }
    if (!sheet.ready) return;
    if (sheet.requestedRowId === pendingReveal.rowId) {
      // The server's page for this row does not hold it (it was removed in the meantime).
      setPendingReveal(null);
      return;
    }
    // Only a reveal with a row is kept (revealHere).
    showRow(pendingReveal.rowId!);
  }, [pendingReveal, rows, columns, pending, sheet.error, sheet.ready, sheet.requestedRowId, showRow]);

  // Keep the requested cell in view and move focus to it.
  useLayoutEffect(() => {
    if (!focusRequest || !rows) return;
    const rowIndex = rows.findIndex((row) => row.row_id === focusRequest.rowId);
    const columnIndex = columns.findIndex((column) => column.column_id === focusRequest.columnId);
    const cell = cellAt(tableRef.current, rowIndex, columnIndex);
    setFocusRequest(null);
    if (!cell) return;
    // A reveal (a risk, a position) brings the row's quantity, unit price and total along.
    const keepInView = focusRequest.center
      ? columns.flatMap((column, index) =>
          index !== columnIndex && ARITHMETIC_FIELDS.has(column.mapped_semantic_field ?? '')
            ? [cellAt(tableRef.current, rowIndex, index)].filter((found): found is HTMLTableCellElement => Boolean(found))
            : [],
        )
      : [];
    scrollCellIntoView(scrollerRef.current, cell, { center: focusRequest.center, keepInView });
    if (focusRequest.focus) cell.focus({ preventScroll: true });
    if (focusRequest.flash && !prefersReducedMotion()) {
      setFlashKey(cellKey(focusRequest.rowId, focusRequest.columnId));
      window.clearTimeout(flashTimer.current);
      flashTimer.current = window.setTimeout(() => setFlashKey(null), FLASH_MS);
    }
  }, [focusRequest, rows, columns]);

  useEffect(() => () => window.clearTimeout(flashTimer.current), []);

  const startEdit = (at: GridPosition, character: string | null) => {
    const target = targetAt(at);
    const key = cellKey(target.rowId, target.columnId);
    if (pending[key] !== undefined) return;
    const row = rows![at.row];
    const column = columns[at.column];
    const cell = row.cells[column.column_id] ?? null;
    activate(target);
    setEditing({
      ...target,
      label: t('Edit {cell}', { cell: cellAddress(row, column, cell) }),
      initialText: character ?? rawText(cell),
      selectAll: character === null,
    });
  };

  const commitEdit = (text: string, move: 'left' | 'right' | null, { viaBlur }: { viaBlur: boolean }) => {
    const target = editing;
    setEditing(null);
    if (!target || !rows) return;
    const rowIndex = rows.findIndex((row) => row.row_id === target.rowId);
    const columnIndex = columns.findIndex((column) => column.column_id === target.columnId);
    if (rowIndex >= 0 && columnIndex >= 0) {
      const row = rows[rowIndex];
      const column = columns[columnIndex];
      const cell = row.cells[column.column_id] ?? null;
      const before = rawText(cell);
      if (text !== before.replace(/\r\n?/g, '\n')) {
        saves.save({ ...target, reference: cellAddress(row, column, cell), before, text });
      }
      if (move) {
        const next = targetAt(stepAcross({ row: rowIndex, column: columnIndex }, move, columns.length));
        activate(next);
        setFocusRequest({ ...next, focus: true });
        return;
      }
    }
    if (!viaBlur) setFocusRequest({ ...target, focus: true });
  };

  const cancelEdit = () => {
    const target = editing;
    setEditing(null);
    if (target) setFocusRequest({ ...target, focus: true });
  };

  const closeNote = ({ restoreFocus = false }: { restoreFocus?: boolean } = {}) => {
    setDismissedKey(activeKey);
    if (restoreFocus && active) setFocusRequest({ ...active, focus: true });
  };

  const reloadTable = () => {
    saves.acceptReload();
    sheet.reload();
    onReload?.();
  };

  const selectedKeys = useMemo(() => issueCellKeys(selectedIssue, tableId), [selectedIssue, tableId]);
  let noteIssues: ValidationIssue[] = [];
  if (position && active && !editing) {
    const findings = cellFindings(findingsIndex, tableId, active.rowId, active.columnId);
    const includeSelected =
      sameCell(revealed, active) && !!selectedIssue && issueTouchesRow(selectedIssue, tableId, active.rowId);
    noteIssues = noteFindings(findings, selectedIssue, includeSelected);
  }
  const showNote = !showPdf && showNotes && noteIssues.length > 0 && dismissedKey !== activeKey;
  const anchorRow = position?.row ?? -1;
  const anchorColumn = position?.column ?? -1;
  const getAnchor = useCallback(() => cellAt(tableRef.current, anchorRow, anchorColumn), [anchorRow, anchorColumn]);

  let grid: ReactNode;
  if (sheet.error) {
    grid = (
      <div className="p-4">
        <ErrorState error={sheet.error} title={t('Rows could not be loaded')} onRetry={sheet.reload} />
      </div>
    );
  } else if (!rows) {
    grid = <LoadingState variant="sheet" label={t('Loading rows…')} />;
  } else if (!rows.length) {
    grid = (
      <EmptyState compact headingLevel={3} icon={Rows3} title={t('No rows on this page')} description={t('The table has no rows in this range.')} />
    );
  } else {
    const editingAt =
      editing &&
      (() => {
        const row = rows.findIndex((candidate) => candidate.row_id === editing.rowId);
        const column = columns.findIndex((candidate) => candidate.column_id === editing.columnId);
        return row >= 0 && column >= 0
          ? { row, column, label: editing.label, initialText: editing.initialText, selectAll: editing.selectAll }
          : null;
      })();
    grid = (
      <SheetGrid
        label={t('Sheet {name}', { name: table.name })}
        tableId={tableId}
        columns={columns}
        rows={rows}
        offset={sheet.offset}
        total={total}
        active={position}
        editing={editingAt || null}
        pending={pending}
        flashKey={flashKey}
        findingsIndex={findingsIndex}
        selectedKeys={selectedKeys}
        tableRef={tableRef}
        freezeDescription={scrollerWidth >= FREEZE_DESCRIPTION_MIN_WIDTH}
        onActivate={(at) => activateByUser(targetAt(at))}
        onMove={(at) => {
          const target = targetAt(at);
          activateByUser(target);
          setFocusRequest({ ...target, focus: true });
        }}
        onStartEdit={startEdit}
        onCommitEdit={commitEdit}
        onCancelEdit={cancelEdit}
        onEscape={() => closeNote()}
      />
    );
  }

  const activePending = activeKey ? pending[activeKey] : undefined;
  return (
    <div ref={containerRef} className={fill ? 'relative flex min-h-0 flex-1 flex-col' : 'relative'}>
      <CellBar
        reference={activeReference}
        text={activePending ?? (activeRow ? rawText(activeCell) : null)}
        note={activeRow && activeColumn ? readingNote(activeCell, activeColumn) : null}
        trailing={pdf ? <ViewSwitch view={view} onChange={onViewChange} /> : null}
      />
      {showPdf && pdf ? (
        <SheetPdf source={pdf} target={pdfTarget} fill={fill} />
      ) : (
        <div ref={scrollerRef} className={fill ? SHEET_SCROLLER_FILL : SHEET_SCROLLER}>
          {grid}
        </div>
      )}
      {showNote && activeReference && (
        <SheetNote
          reference={activeReference}
          issues={noteIssues}
          getAnchor={getAnchor}
          scrollerRef={scrollerRef}
          containerRef={containerRef}
          onReview={(issue) => onReview?.(issue)}
          onClose={closeNote}
        />
      )}
      {!showPdf && (
        <div className={SHEET_FOOTER}>
          <SaveStatus status={saves.status} onUndo={saves.undo} onReloadTable={reloadTable} />
          <div className="ml-auto [&>nav]:border-t-0">
            <Pagination offset={sheet.offset} limit={SHEET_PAGE_SIZE} total={total} onChange={sheet.goToPage} itemLabel={t('rows')} />
          </div>
        </div>
      )}
    </div>
  );
}

interface SheetProps {
  datasetId: string;
  table: TableSummary;
  tables?: TableSummary[];
  onTableChange?: (tableId: string) => void;
  revision: number;
  onRevised?: (result: CorrectionsResult) => void;
  onReload?: () => void;
  findingsIndex?: CellIndex;
  selectedIssue?: ValidationIssue | null;
  reveal?: Reveal | null;
  onReview?: (issue: ValidationIssue) => void;
  showNotes?: boolean;
  onCellFindings?: (found: readonly ValidationIssue[]) => void;
  onRowsLoaded?: (rows: Row[]) => void;
  actions?: ReactNode;
  pdf?: PdfSource | null;
  fill?: boolean;
  fullScreen?: boolean;
  onFullScreenChange?: (on: boolean) => void;
}

/**
 * The bill as a live sheet: one table of the dataset, 100 rows per page, editable cell by
 * cell. Each edit is saved at once as the dataset's next revision (`correctCells` with
 * `expected_revision`); the uploaded file is never changed. Open findings of the chosen run
 * wash their cells red, the selected issue's cells are ringed, and the active (or revealed)
 * cell's findings appear in a note with a Review button. With `showNotes={false}` (the side
 * panel shows the risk instead) there is no note: moving to a flagged cell calls
 * `onCellFindings(findings)`.
 *
 * - `reveal` (`{ tableId, rowId, columnId, edit, nonce }`): on a new nonce, go to that cell
 *   (another table through `onTableChange`, another page through the rows endpoint's
 *   `row_id`), make it active, centre it and open its note, or its editor with `edit`.
 *   Without `columnId` the row's first cell is used.
 * - `onRevised(result)` after a save that changed cells, with the `correctCells` answer.
 * - `onReload()` from "Reload table" after a 409; the sheet reloads its rows itself.
 * - `onRowsLoaded(rows)` with the page's rows whenever they change (a new page, or the page
 *   with the saved rows replaced).
 * - `actions`: the header buttons on the right (validation and model controls).
 * - `pdf`: the file's PDF (see pdfLinks.ts). With one, a Table / PDF switch sits on the right of
 *   the cell bar; the PDF view shows the printed bill in the same box, with the active cell
 *   highlighted. A reveal that opens a cell's editor goes back to the table.
 * - `fill`: the box takes the height its flex container leaves it, and the table or the PDF
 *   scrolls inside; without it the scrolling area has a fixed height.
 * - `fullScreen` and `onFullScreenChange(on)`: with the callback, a Full screen button sits at
 *   the right of the header. In full screen the box covers the window (the table or the PDF
 *   taking all the height), and a flagged cell shows its note here, since the side panel is
 *   covered; Review leaves full screen and opens the risk there.
 */
export function Sheet({
  datasetId,
  table,
  tables = [],
  onTableChange,
  revision,
  onRevised,
  onReload,
  findingsIndex = NO_CELL_FINDINGS,
  selectedIssue = null,
  reveal = null,
  onReview,
  showNotes = true,
  onCellFindings,
  onRowsLoaded,
  actions = null,
  pdf = null,
  fill = false,
  fullScreen = false,
  onFullScreenChange,
}: SheetProps) {
  const headingId = useId();
  const [view, setView] = useState<View>('table');
  const [editNonce, setEditNonce] = useState<Reveal['nonce'] | null>(null);
  // Approve on a risk opens the cell's editor, which only the table shows.
  if (reveal?.edit && reveal.nonce !== editNonce) {
    setEditNonce(reveal.nonce);
    if (view !== 'table') setView('table');
  }
  const tableId = table.table_id;
  const revealTableId = reveal?.rowId ? reveal.tableId : null;
  const onTableChangeRef = useLatest(onTableChange);

  // A cell of another table: switch to it; the new table's body then reveals the cell.
  useEffect(() => {
    if (revealTableId && revealTableId !== tableId && tables.some((candidate) => candidate.table_id === revealTableId)) {
      onTableChangeRef.current?.(revealTableId);
    }
    // Only for a new reveal, not when the user switches tables afterwards.
  }, [reveal?.nonce]);

  return (
    <section
      aria-labelledby={headingId}
      className={cx(
        'bg-surface',
        // The part that grows to the window and back (useFullScreen, index.css).
        onFullScreenChange && '[view-transition-name:full-screen]',
        fullScreen ? 'fixed inset-0 z-40 flex flex-col' : cx('rounded-lg border border-hairline', fill && 'flex min-h-0 flex-1 flex-col'),
      )}
    >
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-hairline px-4 py-1.5">
        <div className="flex min-w-0 items-center gap-3">
          <h2 id={headingId} className="truncate text-headline text-ink" title={table.name}>
            {table.name}
          </h2>
          {tables.length > 1 && onTableChange && (
            <Select
              label={t('Table')}
              hideLabel
              value={tableId}
              options={tables.map((candidate) => ({ value: candidate.table_id, label: candidate.name }))}
              onChange={onTableChange}
              className="w-48"
            />
          )}
        </div>
        {(actions || onFullScreenChange) && (
          <div className="flex flex-wrap items-center gap-2">
            {actions}
            {onFullScreenChange && (
              <IconButton
                icon={fullScreen ? Minimize2 : Maximize2}
                label={fullScreen ? 'Exit full screen' : 'Full screen'}
                onPress={() => onFullScreenChange(!fullScreen)}
              />
            )}
          </div>
        )}
      </div>
      <SheetBody
        key={`${datasetId}\u0000${tableId}`}
        datasetId={datasetId}
        table={table}
        revision={revision}
        onRevised={onRevised}
        onReload={onReload}
        findingsIndex={findingsIndex}
        selectedIssue={selectedIssue}
        reveal={reveal}
        onReview={(issue) => {
          if (fullScreen) onFullScreenChange?.(false);
          onReview?.(issue);
        }}
        showNotes={showNotes || fullScreen}
        onCellFindings={fullScreen ? undefined : onCellFindings}
        onRowsLoaded={onRowsLoaded}
        pdf={pdf}
        view={pdf ? view : 'table'}
        onViewChange={setView}
        fill={fullScreen || fill}
      />
    </section>
  );
}
