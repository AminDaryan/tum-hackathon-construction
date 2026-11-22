import { X } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { Button } from '../../../components/Button.tsx';
import { IconButton } from '../../../components/IconButton.tsx';
import { t } from '../../../i18n/messages.ts';
import { cx } from '../../../utils/classNames.ts';
import { formatCount } from '../../../utils/format.ts';
import { firstSentence } from './cellText.ts';
import { isCellVisible } from './sheetDom.ts';
import { NOTE_LIMIT } from './sheetFindings.ts';
import type { ValidationIssue } from '../../../services/apiTypes.ts';

const NOTE_WIDTH = 288;
const GAP = 4;
const EDGE = 8;

/** Where the note stands in its container; `visible` is false while its cell is scrolled away. */
interface NotePosition {
  top: number;
  left: number;
  visible: boolean;
}

function samePosition(a: NotePosition | null, b: NotePosition | null) {
  return a && b && a.top === b.top && a.left === b.left && a.visible === b.visible;
}

/**
 * Where the note goes inside `container` (which is `position: relative`): below the cell, or
 * above it when the viewport has no room below; never past the container's sides. `visible`
 * is false while the cell is scrolled out of the grid's free area.
 */
function notePosition({
  container,
  scroller,
  anchor,
  note,
}: {
  container: HTMLElement;
  scroller: HTMLElement;
  anchor: HTMLElement;
  note: HTMLElement | null;
}): NotePosition {
  const box = container.getBoundingClientRect();
  const cell = anchor.getBoundingClientRect();
  const height = note?.offsetHeight ?? 0;
  const fitsBelow = cell.bottom + GAP + height <= window.innerHeight;
  const fitsAbove = cell.top - GAP - height >= 0;
  const below = fitsBelow || !fitsAbove;
  const maxLeft = Math.max(EDGE, box.width - NOTE_WIDTH - EDGE);
  return {
    top: Math.round(below ? cell.bottom - box.top + GAP : cell.top - box.top - GAP - height),
    left: Math.round(Math.min(Math.max(cell.left - box.left, EDGE), maxLeft)),
    visible: isCellVisible(scroller, anchor),
  };
}

interface SheetNoteProps {
  reference: string;
  issues: ValidationIssue[];
  getAnchor: () => HTMLElement | null;
  scrollerRef: RefObject<HTMLElement | null>;
  containerRef: RefObject<HTMLElement | null>;
  onReview: (issue: ValidationIssue) => void;
  onClose: (options?: { restoreFocus?: boolean }) => void;
}

/**
 * The note anchored to a cell (the "tooltip" of a finding): up to three findings of the cell
 * with their title, the first sentence of their explanation and a Review button, and how many
 * more there are. It is a non-modal dialog placed right after the grid in the DOM, so Tab
 * reaches it from the active cell. It follows the cell when the grid scrolls or the window is
 * resized, and hides while the cell is scrolled out of view. Escape or Close dismiss it.
 *
 * `getAnchor()` returns the cell element; `scrollerRef` is the grid's scroll area and
 * `containerRef` the positioned wrapper the note is placed in.
 */
export function SheetNote({
  reference,
  issues,
  getAnchor,
  scrollerRef,
  containerRef,
  onReview,
  onClose,
}: SheetNoteProps) {
  const noteRef = useRef<HTMLDivElement>(null);
  const idPrefix = useId();
  const [position, setPosition] = useState<NotePosition | null>(null);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const scroller = scrollerRef.current;
    const anchor = getAnchor();
    if (!container || !scroller || !anchor) return;
    const next = notePosition({ container, scroller, anchor, note: noteRef.current });
    setPosition((current) => (samePosition(current, next) ? current : next));
  });

  useEffect(() => {
    const scroller = scrollerRef.current;
    const update = () => {
      const container = containerRef.current;
      const anchor = getAnchor();
      if (!container || !scroller || !anchor) return;
      const next = notePosition({ container, scroller, anchor, note: noteRef.current });
      setPosition((current) => (samePosition(current, next) ? current : next));
    };
    scroller?.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    return () => {
      scroller?.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, [getAnchor, scrollerRef, containerRef]);

  const shown = issues.slice(0, NOTE_LIMIT);
  const more = issues.length - shown.length;
  return (
    <div
      ref={noteRef}
      role="dialog"
      aria-label={t('Findings for cell {reference}', { reference })}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          onClose({ restoreFocus: true });
        }
      }}
      style={position ? { top: position.top, left: position.left, width: NOTE_WIDTH } : { top: 0, left: 0, width: NOTE_WIDTH }}
      className={cx(
        'absolute z-30 rounded-md border border-hairline border-l-violation bg-surface text-left shadow-popover',
        (!position || !position.visible) && 'invisible',
      )}
    >
      <div className="flex items-start justify-between gap-2 pl-3">
        <p className="pt-3 text-caption text-ink-secondary sheet-figures">{t('Cell {reference}', { reference })}</p>
        <IconButton icon={X} label={t('Close note')} onPress={() => onClose({ restoreFocus: true })} />
      </div>
      <ul className="flex flex-col gap-3 px-3 pb-3">
        {shown.map((issue) => {
          const titleId = `${idPrefix}-${issue.issue_id}`;
          return (
            <li key={issue.issue_id} className="flex flex-col items-start gap-1">
              <p id={titleId} className="line-clamp-2 text-callout font-semibold text-ink">
                {issue.title}
              </p>
              <p className="line-clamp-2 text-caption text-ink-secondary">{firstSentence(issue.explanation)}</p>
              <Button aria-describedby={titleId} className="mt-1" onPress={() => onReview(issue)}>
                {t('Review')}
              </Button>
            </li>
          );
        })}
      </ul>
      {more > 0 && <p className="px-3 pb-3 text-caption text-ink-secondary">{t('and {count} more in the Risks tab', { count: formatCount(more) })}</p>}
    </div>
  );
}
