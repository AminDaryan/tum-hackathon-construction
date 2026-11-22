import { cx } from '../utils/classNames.ts';

interface SkeletonProps {
  className?: string;
}

/**
 * A placeholder shape that stands in for content while it loads. Decorative: the loading state
 * around it (`LoadingState`) says what is loading. The pulse stops when the reader asks for
 * reduced motion (the global rule in index.css).
 */
export function Skeleton({ className }: SkeletonProps) {
  return <div aria-hidden="true" className={cx('animate-pulse rounded-md bg-skeleton', className)} />;
}

/** Widths that repeat down a list, so the placeholder reads as text rather than as bars. */
const LINE_WIDTHS = ['w-3/4', 'w-full', 'w-2/3', 'w-5/6', 'w-1/2'];
const lineWidth = (index: number) => LINE_WIDTHS[index % LINE_WIDTHS.length];
const range = (count: number) => Array.from({ length: count }, (_, index) => index);

interface SkeletonTextProps {
  lines?: number;
  className?: string;
}

/** A few lines of text. */
export function SkeletonText({ lines = 3, className }: SkeletonTextProps) {
  return (
    <div aria-hidden="true" className={cx('flex flex-col gap-2.5', className)}>
      {range(lines).map((index) => (
        <Skeleton key={index} className={cx('h-3', lineWidth(index))} />
      ))}
    </div>
  );
}

interface SkeletonListProps {
  rows?: number;
  className?: string;
}

/** Rows of a list: a short title line and a longer caption under it. */
export function SkeletonList({ rows = 4, className }: SkeletonListProps) {
  return (
    <ul aria-hidden="true" className={cx('divide-y divide-hairline', className)}>
      {range(rows).map((index) => (
        <li key={index} className="flex items-center gap-3 py-3">
          <Skeleton className="size-5 shrink-0 rounded-sm" />
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <Skeleton className={cx('h-3.5', index % 2 ? 'w-1/3' : 'w-2/5')} />
            <Skeleton className={cx('h-3', lineWidth(index))} />
          </div>
        </li>
      ))}
    </ul>
  );
}

interface SkeletonTableProps {
  rows?: number;
  columns?: number;
  className?: string;
}

/** A table: a header row and `rows` rows of `columns` cells, the columns lined up. */
export function SkeletonTable({ rows = 5, columns = 5, className }: SkeletonTableProps) {
  const cell = (column: number) => cx('flex min-w-0', column === 0 ? 'w-40 shrink-0' : 'flex-1', column > 2 && 'max-md:hidden');
  return (
    <div aria-hidden="true" className={cx('flex flex-col', className)}>
      <div className="flex gap-6 border-b border-hairline px-4 py-3">
        {range(columns).map((column) => (
          <div key={column} className={cell(column)}>
            <Skeleton className={cx('h-3', column === 0 ? 'w-16' : 'w-12')} />
          </div>
        ))}
      </div>
      {range(rows).map((row) => (
        <div key={row} className="flex items-center gap-6 border-b border-hairline px-4 py-3.5 last:border-b-0">
          {range(columns).map((column) => (
            <div key={column} className={cell(column)}>
              <Skeleton className={cx('h-3.5', column === 0 ? 'w-32' : lineWidth(row + column))} />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
