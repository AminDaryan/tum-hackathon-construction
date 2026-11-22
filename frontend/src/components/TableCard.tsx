import { useId, useLayoutEffect, useRef, useState } from 'react';
import { cx } from '../utils/classNames.ts';
import { DataTable, type DataTableColumn } from './DataTable.tsx';
import { Pagination } from './Pagination.tsx';
import { Skeleton } from './Skeleton.tsx';
import type { CSSProperties, ReactNode, RefObject } from 'react';

/** The height of a body row and of the column header row, in rem. */
export const TABLE_ROW_REM = 3.5;
/** The height of a row with two lines (a title over its file or bill). */
export const TWO_LINE_ROW_REM = 3.75;
const HEADER_REM = 2.25;
/** The fewest body rows a `fill` box keeps room for, however little height its parent gives. */
const FILL_MIN_ROWS = 2;
/** With `fitRows`: the room for the empty or failed line, and the grey rows while loading. */
const FIT_STATUS_ROWS = 3;
const FIT_LOADING_ROWS = 5;

/**
 * Client-side pages of `rows`: the rows of the page shown, its offset and a setter. A shorter
 * list (a filter, a removed row) keeps the offset on a page that exists.
 */
export function usePagedRows<Row>(rows: Row[], pageSize: number) {
  const [offset, setOffset] = useState(0);
  const last = Math.max(0, Math.floor((rows.length - 1) / pageSize) * pageSize);
  const start = Math.min(offset, last);
  return { rows: rows.slice(start, start + pageSize), offset: start, total: rows.length, setOffset };
}

/**
 * Tells `onChange` how many body rows of `rowHeight` rem fit under the column header in the
 * element `ref` points to, now and whenever it is resized. Silent while the element has no height
 * (not laid out yet, or in a test without layout).
 */
function useFittedRows(ref: RefObject<HTMLDivElement | null> | null, rowHeight: number, onChange?: (rows: number) => void) {
  useLayoutEffect(() => {
    const area = ref?.current;
    if (!area || !onChange || typeof ResizeObserver === 'undefined') return undefined;
    const measure = () => {
      if (!area.clientHeight) return;
      const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
      onChange(Math.max(1, Math.floor((area.clientHeight - HEADER_REM * rem) / (rowHeight * rem))));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    return () => observer.disconnect();
  }, [ref, rowHeight, onChange]);
}

interface TableCardProps<Row> {
  title: string;
  count?: number | null;
  description?: ReactNode;
  actions?: ReactNode;
  /** Content between the header and the table, such as the figures the table's rows add up to. */
  summary?: ReactNode;
  headingLevel?: 2 | 3;
  columns: DataTableColumn<Row>[];
  rows: Row[];
  getRowKey: (row: Row) => string;
  caption?: string;
  onRowActivate?: (row: Row) => void;
  selectedKey?: string;
  rowClassName?: (row: Row) => string | undefined;
  disabledKeys?: string[];
  pageSize: number;
  rowHeight?: number;
  offset?: number;
  total?: number | null;
  onOffsetChange?: (offset: number) => void;
  itemLabel?: string;
  status?: string | null;
  statusAction?: ReactNode;
  loading?: boolean;
  loadingLabel?: string;
  footer?: ReactNode;
  /** The box takes its parent's height and reports through `onPageSizeChange` how many rows fit. */
  fill?: boolean;
  onPageSizeChange?: (pageSize: number) => void;
  /** The table ends after the page's last row instead of keeping room for `pageSize` rows. */
  fitRows?: boolean;
  className?: string;
}

/**
 * The one box for a table of items, used by every list of items in the app: a header row
 * (title with the count, an optional description and the actions at its right), the table, and
 * the pages under it. The table area is always `pageSize` rows tall, so the box keeps its height
 * whatever the number of items; a row's content that does not fit scrolls inside. `status` (one
 * line: why there are no rows, empty or failed) shows under the column header in the middle of
 * the rows' space, the same way in every table, with `statusAction` (a Retry) under it;
 * `loading` shows the real column header over `pageSize` rows of grey bars instead, and
 * `loadingLabel` says what loads for screen readers. `footer` goes under the pages.
 *
 * Paging is controlled: `offset`, `total` and `onOffsetChange` (see `usePagedRows` for rows held
 * in the browser). Without `onOffsetChange` the box shows no pages. With `fill` the box takes its
 * parent's height instead (room for two rows and the pages at least, more than a low parent
 * gives), and `onPageSizeChange` tells the caller
 * how many rows fit in it. With `fitRows` the table is as tall as the rows of the page (three
 * rows' room for the empty or failed line, five grey rows while loading), so a short list ends
 * after its last row. `summary` goes between the header and the table.
 */
export function TableCard<Row>({
  title,
  count = null,
  description = null,
  actions = null,
  summary = null,
  headingLevel = 2,
  columns,
  rows,
  getRowKey,
  caption,
  onRowActivate,
  selectedKey,
  rowClassName,
  disabledKeys,
  pageSize,
  rowHeight = TABLE_ROW_REM,
  offset = 0,
  total = null,
  onOffsetChange,
  itemLabel,
  status = null,
  statusAction = null,
  loading = false,
  loadingLabel,
  footer = null,
  fill = false,
  onPageSizeChange,
  fitRows = false,
  className,
}: TableCardProps<Row>) {
  const headingId = useId();
  const Heading = `h${headingLevel}` as const;
  const loadingRows = fitRows ? Math.min(pageSize, FIT_LOADING_ROWS) : pageSize;
  let bodyRows = pageSize;
  if (fitRows) bodyRows = loading ? loadingRows : status ? FIT_STATUS_ROWS : Math.max(rows.length, 1);
  const height = `${HEADER_REM + bodyRows * rowHeight}rem`;
  const areaRef = useRef<HTMLDivElement>(null);
  useFittedRows(fill ? areaRef : null, rowHeight, onPageSizeChange);
  return (
    <section
      aria-labelledby={headingId}
      // Filling, the box never gets shorter than its header, two rows and its pages: a lower
      // parent lets it overflow, so the page scrolls instead of cutting the pages off.
      className={cx('flex min-w-0 flex-col overflow-hidden rounded-lg border border-hairline bg-surface', fill && 'h-full min-h-fit', className)}
    >
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-hairline py-2 pl-4 pr-2">
        <div className="min-w-0">
          <Heading id={headingId} className="text-headline text-ink">
            {/* A title that is still loading: a grey shape of its size. */}
            {title || (loading && <Skeleton className="my-1 h-4 w-40" />)}
            {count !== null && <span className="font-normal text-ink-secondary"> ({count})</span>}
          </Heading>
          {description && <div className="text-caption text-ink-secondary">{description}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {summary && <div className="border-b border-hairline p-4">{summary}</div>}
      <div
        ref={areaRef}
        className={cx('relative min-h-0', fill && 'flex-1')}
        style={fill ? { minHeight: `${HEADER_REM + FILL_MIN_ROWS * rowHeight}rem` } : { height }}
      >
        {/* Filling, the rows sit over the area so that they never make it, and the box, taller. */}
        <div className={fill ? 'absolute inset-0' : 'h-full'}>
          {loading ? (
            <div role="status" className="h-full [&_tbody_tr]:h-(--row-height)" style={{ '--row-height': `${rowHeight}rem` } as CSSProperties}>
              <span className="sr-only">{loadingLabel ?? title}</span>
              <DataTable columns={columns} rows={[]} getRowKey={String} caption={caption ?? title} maxHeightClass="h-full" placeholderRows={loadingRows} />
            </div>
          ) : status ? (
            <div className="flex h-full flex-col">
              {/* The column header stays, so an empty or failed table looks like the table it is. */}
              <div aria-hidden="true">
                <DataTable columns={columns} rows={[]} getRowKey={String} caption={caption ?? title} />
              </div>
              <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 overflow-auto px-4 text-center">
                <p className="text-body text-ink-secondary">{status}</p>
                {statusAction}
              </div>
            </div>
          ) : (
            // Every body row is `rowHeight` tall (more than the 44/48 px hit height rows already have).
            <div className="h-full [&_tbody_tr]:h-(--row-height)" style={{ '--row-height': `${rowHeight}rem` } as CSSProperties}>
              <DataTable
                columns={columns}
                rows={rows}
                getRowKey={getRowKey}
                caption={caption ?? title}
                onRowActivate={onRowActivate}
                selectedKey={selectedKey}
                rowClassName={rowClassName}
                disabledKeys={disabledKeys}
                maxHeightClass="h-full"
                // A page with room under its rows closes its last row too; a full one ends on the pages' border.
                lastRowDivider={!fitRows && rows.length < pageSize}
              />
            </div>
          )}
        </div>
      </div>
      {onOffsetChange && loading && (
        <div aria-hidden="true" className="flex min-h-15 items-center border-t border-hairline px-4 py-2 pointer-coarse:min-h-16">
          <Skeleton className="h-3.5 w-28" />
        </div>
      )}
      {onOffsetChange && !loading && (
        <Pagination
          offset={offset}
          limit={pageSize}
          total={total ?? rows.length}
          onChange={onOffsetChange}
          itemLabel={itemLabel ?? ''}
          className="min-h-15 pointer-coarse:min-h-16"
          showEmpty
        />
      )}
      {footer && <div className="border-t border-hairline px-4 py-2">{footer}</div>}
    </section>
  );
}
