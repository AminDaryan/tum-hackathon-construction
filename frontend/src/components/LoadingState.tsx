import { cx } from '../utils/classNames.ts';
import { Skeleton, SkeletonList, SkeletonTable, SkeletonText } from './Skeleton.tsx';

const range = (count: number) => Array.from({ length: count }, (_, index) => index);

/** Columns of the sheet placeholder: the row number, then cells of typical bill widths. */
const SHEET_COLUMNS = ['w-12', 'w-24', 'w-72', 'w-28', 'w-20', 'w-16', 'w-20', 'w-24'];

interface SheetShapeProps { rows: number }

/** Cells with grid lines, decorative; the loading state around it says what loads. */
export function SheetShape({ rows }: SheetShapeProps) {
  return (
    <div aria-hidden="true" className="min-w-max">
      {range(rows + 1).map((row) => (
        <div key={row} className={cx('flex h-8 border-b border-hairline', row === 0 && 'bg-surface-muted')}>
          {SHEET_COLUMNS.map((width, column) => (
            <div key={column} className={cx('flex shrink-0 items-center border-r border-hairline px-2', width)}>
              <Skeleton className={cx('h-3', column === 0 ? 'w-4' : row % 3 === 1 && column > 3 ? 'w-1/3' : 'w-2/3')} />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function PdfShape() {
  return (
    <div aria-hidden="true" className="flex justify-center p-4">
      <div className="flex aspect-[210/297] w-full max-w-2xl flex-col gap-6 rounded-sm bg-surface p-8 shadow-sm">
        <Skeleton className="h-4 w-1/2" />
        <SkeletonText lines={4} />
        <SkeletonText lines={5} />
        <SkeletonText lines={3} />
      </div>
    </div>
  );
}

interface LoadingStateProps {
  label: string;
  variant?: 'text' | 'list' | 'table' | 'sheet' | 'pdf' | 'block';
  rows?: number;
  compact?: boolean;
  showLabel?: boolean;
  className?: string;
}

/**
 * The placeholder of a component that is loading: grey shapes in the layout the content will
 * have, so the page does not jump when it arrives. `variant` picks the shape: `text` (lines),
 * `list` (rows with a caption), `table`, `sheet` (cells with grid lines), `pdf` (a page) or
 * `block` (fills its container). A page loading as a whole builds its own placeholder in its own
 * layout instead.
 *
 * The status says what is loading for screen readers (`label`); `showLabel` also shows it, for
 * a message the reader should see, such as a validation that is still running. No percentage is
 * ever shown: the API reports no progress, so none is invented.
 */
export function LoadingState({
  label,
  variant = 'text',
  rows,
  compact = false,
  showLabel = false,
  className,
}: LoadingStateProps) {
  let shape;
  switch (variant) {
    case 'list':
      shape = <SkeletonList rows={rows ?? (compact ? 3 : 4)} />;
      break;
    case 'table':
      shape = <SkeletonTable rows={rows ?? 5} />;
      break;
    case 'sheet':
      shape = <SheetShape rows={rows ?? 12} />;
      break;
    case 'pdf':
      shape = <PdfShape />;
      break;
    case 'block':
      shape = <Skeleton className="size-full min-h-40 rounded-none" />;
      break;
    default:
      shape = <SkeletonText lines={rows ?? (compact ? 2 : 3)} />;
  }
  return (
    <div role="status" className={cx('flex flex-col gap-3', variant === 'block' && 'size-full', className)}>
      {showLabel ? <p className="text-callout text-ink-secondary">{label}</p> : <span className="sr-only">{label}</span>}
      {shape}
    </div>
  );
}
