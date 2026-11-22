import { cx } from '../../../utils/classNames.ts';
import { pluralize } from '../../../utils/format.ts';
import { UNREMARKABLE_PARSE_STATUSES } from '../../../utils/vocabulary.ts';
import { ParseMarker } from '../ParseMarker.tsx';
import { isNumberCell, rawText } from './cellText.ts';
import { FROZEN_COLUMN } from './sheetLayout.ts';
import type { ReactNode } from 'react';
import type { Cell } from '../../../services/apiTypes.ts';

// One inset ring per state, as box shadows so they never take layout space: Red pen for the
// selected issue's cells (thicker while it flashes), Cursor teal for the active cell, inside
// the red one when a cell is both.
const RING = {
  active: 'shadow-[inset_0_0_0_2px_var(--color-accent)]',
  issue: 'shadow-[inset_0_0_0_2px_var(--color-violation)]',
  issueFlash: 'shadow-[inset_0_0_0_4px_var(--color-violation)]',
  both: 'shadow-[inset_0_0_0_2px_var(--color-violation),inset_0_0_0_4px_var(--color-accent)]',
  activeFlash: 'shadow-[inset_0_0_0_4px_var(--color-accent)]',
};

// The red-pen corner tick of a cell with an open finding.
const TICK =
  "after:pointer-events-none after:absolute after:right-0 after:top-0 after:size-[7px] after:bg-violation after:content-[''] after:[clip-path:polygon(0_0,100%_0,100%_100%)]";

function ringClass({
  active,
  inSelectedIssue,
  flashing,
}: Pick<SheetCellProps, 'active' | 'inSelectedIssue' | 'flashing'>) {
  if (inSelectedIssue && active && !flashing) return RING.both;
  if (inSelectedIssue) return flashing ? RING.issueFlash : RING.issue;
  if (active) return flashing ? RING.activeFlash : RING.active;
  return null;
}

function backgroundClass({
  inSelectedIssue,
  openFindings,
  tone,
}: Pick<SheetCellProps, 'inSelectedIssue' | 'openFindings' | 'tone'>) {
  if (inSelectedIssue) return 'bg-issue-cell-strong';
  if (openFindings > 0) return 'bg-issue-cell';
  return tone === 'section' ? 'bg-surface-muted' : 'bg-surface';
}

interface SheetCellProps {
  /** A column kept in view beside the row numbers while the sheet scrolls sideways. */
  frozen?: 'item' | 'description';
  cell?: Cell | null;
  rowIndex: number;
  columnIndex: number;
  tabbable: boolean;
  active: boolean;
  openFindings: number;
  inSelectedIssue: boolean;
  flashing: boolean;
  pendingText?: string | null;
  tone?: 'plain' | 'section';
  children?: ReactNode;
}

/**
 * One cell of the sheet: the text as it stands in the file, a parse marker when the app could
 * not read it cleanly, and the marks of the findings on it. A cell with open findings is washed
 * red, carries a corner tick and says how many findings it has to screen readers; the selected
 * issue's cells are ringed in red. While a save runs the cell shows the new text dimmed.
 *
 * Clicks, focus and keys are handled by the grid; `rowIndex` and `columnIndex` tell it which
 * cell an event came from. `children` is the editor while the cell is being edited.
 */
export function SheetCell({
  cell = null,
  rowIndex,
  columnIndex,
  tabbable,
  active,
  openFindings,
  inSelectedIssue,
  flashing,
  pendingText = null,
  tone = 'plain',
  children = null,
  frozen,
}: SheetCellProps) {
  const numeric = isNumberCell(cell);
  const saving = pendingText !== null;
  const text = saving ? pendingText : rawText(cell);
  const marker =
    cell && !saving && !UNREMARKABLE_PARSE_STATUSES.has(cell.parse_status) ? (
      <ParseMarker status={cell.parse_status} note={cell.parse_note} marker={cell.marker} />
    ) : null;
  return (
    <td
      role="gridcell"
      tabIndex={tabbable ? 0 : -1}
      data-row-index={rowIndex}
      data-column-index={columnIndex}
      aria-busy={saving || undefined}
      className={cx(
        frozen ? cx('sticky z-[1]', FROZEN_COLUMN[frozen]) : 'relative',
        'h-8 cursor-cell whitespace-nowrap border-b border-r border-hairline px-2 py-0 align-middle text-callout sheet-figures outline-none transition-shadow duration-300',
        numeric && 'text-right',
        backgroundClass({ inSelectedIssue, openFindings, tone }),
        ringClass({ active, inSelectedIssue, flashing }),
        openFindings > 0 && TICK,
      )}
    >
      <div className={cx('flex items-center gap-1', frozen ? 'min-w-0' : 'min-w-[72px] max-w-[320px]', numeric && 'flex-row-reverse')}>
        <span className={cx('truncate', saving && 'text-ink-tertiary')}>{text}</span>
        {marker}
      </div>
      {openFindings > 0 && <span className="sr-only">, {pluralize(openFindings, 'finding')}</span>}
      {children}
    </td>
  );
}
