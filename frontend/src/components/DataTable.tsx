import { Cell, Column, Row, Table, TableBody, TableHeader } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { HIT_HEIGHT } from './hitTarget.ts';
import { Skeleton } from './Skeleton.tsx';
import { t } from '../i18n/messages.ts';
import type { ReactNode } from 'react';

const ALIGN_CLASSES: Readonly<Record<string, string>> = { left: 'text-left', right: 'text-right', center: 'text-center' };
/** Widths of the first column's bars while loading, varied so they read as names. */
const PLACEHOLDER_FIRST = ['w-40', 'w-32', 'w-48'];

export interface DataTableColumn<Row> {
  key: string;
  header: ReactNode;
  render: (row: Row) => ReactNode;
  align?: 'left' | 'right' | 'center';
  /** extra classes for body cells */
  className?: string;
  headerClassName?: string;
  /** The width class of the column's grey bar while the rows load (`w-16` by default). */
  placeholderWidth?: string;
}

interface DataTableProps<Row> {
  columns: DataTableColumn<Row>[];
  rows: Row[];
  getRowKey: (row: Row) => string;
  caption: string;
  onRowActivate?: (row: Row) => void;
  selectedKey?: string;
  rowClassName?: (row: Row) => string | undefined;
  /** Rows that cannot be activated (shown, but not opened). */
  disabledKeys?: string[];
  dense?: boolean;
  maxHeightClass?: string;
  /** While loading: this many rows of grey bars under the real header, instead of `rows`. */
  placeholderRows?: number;
  /** Keep the divider under the last row (for a table with room below its rows). */
  lastRowDivider?: boolean;
}

/**
 * Accessible data table with a column config and a sticky header inside its own scroll area.
 *
 * Without `onRowActivate` it is a plain semantic table. With it, it is a React Aria Table (a
 * grid): arrow keys move between rows and cells, Home/End and Page Up/Down work, and Enter or a
 * click activates a row. Keys pressed inside controls within a row are left alone.
 */
export function DataTable<Row>({
  columns,
  rows,
  getRowKey,
  caption,
  onRowActivate,
  selectedKey,
  rowClassName,
  disabledKeys,
  dense = false,
  maxHeightClass = 'max-h-[70dvh]',
  placeholderRows = 0,
  lastRowDivider = false,
}: DataTableProps<Row>) {
  const interactive = typeof onRowActivate === 'function' && !placeholderRows;
  const byKey = new Map(rows.map((row) => [getRowKey(row), row]));
  const headerClass = (column: DataTableColumn<Row>) =>
    cx(
      'sticky top-0 z-10 h-9 whitespace-nowrap border-b border-hairline bg-surface-muted px-3 text-caption font-semibold text-ink-secondary outline-none',
      ALIGN_CLASSES[column.align ?? 'left'],
      column.headerClassName,
    );
  const cellClass = (column: DataTableColumn<Row>, focusVisible = false) =>
    cx(
      'border-b border-hairline px-3 align-middle text-body text-ink outline-none',
      dense ? 'py-1.5' : 'py-2.5',
      ALIGN_CLASSES[column.align ?? 'left'],
      focusVisible && 'outline-2 -outline-offset-2 outline-focus',
      column.className,
    );
  const tableClass = cx(
    'w-full border-separate border-spacing-0 text-left outline-none',
    !lastRowDivider && '[&_tbody_tr:last-child>td]:border-b-0',
  );

  // While loading: the real header over rows of grey bars, so the table does not move when the
  // rows arrive. Decorative; the loading state around it names what is loading.
  if (placeholderRows) {
    return (
      <div aria-hidden="true" className={cx('relative overflow-hidden', maxHeightClass)}>
        <table className={tableClass}>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key} scope="col" className={headerClass(column)}>
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: placeholderRows }, (_, row) => (
              <tr key={row}>
                {columns.map((column, index) => (
                  <td key={column.key} className={cellClass(column)}>
                    <Skeleton
                      className={cx(
                        'h-3.5',
                        column.placeholderWidth ?? (index === 0 ? PLACEHOLDER_FIRST[row % 3] : 'w-16'),
                        column.align === 'right' && 'ml-auto',
                        column.align === 'center' && 'mx-auto',
                      )}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // A table nobody acts on stays a plain table: a grid would add keyboard stops for nothing.
  if (!interactive) {
    return (
      <div className={cx('relative overflow-auto', maxHeightClass)}>
        <table className={tableClass}>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key} scope="col" className={headerClass(column)}>
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={getRowKey(row)} data-row-key={getRowKey(row)} className={rowClassName?.(row)}>
                {columns.map((column) => (
                  <td key={column.key} className={cellClass(column)}>
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className={cx('relative overflow-auto', maxHeightClass)}>
      <Table
        aria-label={t('{caption}. Press Enter on a row to open it.', { caption })}
        onRowAction={(key) => onRowActivate?.(byKey.get(String(key))!)}
        disabledKeys={disabledKeys}
        disabledBehavior="all"
        className={tableClass}
      >
        <TableHeader>
          {columns.map((column, index) => (
            <Column
              key={column.key}
              id={column.key}
              isRowHeader={index === 0}
              className={headerClass(column)}
            >
              {column.header}
            </Column>
          ))}
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const key = getRowKey(row);
            const selected = selectedKey !== undefined && selectedKey === key;
            return (
              <Row
                key={key}
                id={key}
                data-row-key={key}
                aria-current={selected ? 'true' : undefined}
                className={({ isFocusVisible, isDisabled }) =>
                  cx(
                    'outline-none transition-colors',
                    isDisabled ? 'cursor-not-allowed' : 'cursor-pointer hover:bg-state-hover',
                    HIT_HEIGHT,
                    isFocusVisible && 'bg-accent-subtle outline-2 -outline-offset-2 outline-focus',
                    selected && 'bg-accent-subtle hover:bg-accent-subtle',
                    rowClassName?.(row),
                  )
                }
              >
                {columns.map((column) => (
                  <Cell
                    key={column.key}
                    className={({ isFocusVisible }) => cellClass(column, isFocusVisible)}
                  >
                    {column.render(row)}
                  </Cell>
                ))}
              </Row>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
