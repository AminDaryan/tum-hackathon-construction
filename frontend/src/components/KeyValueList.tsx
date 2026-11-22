import { Fragment } from 'react';
import { cx } from '../utils/classNames.ts';
import type { ReactNode } from 'react';

const EMPTY_VALUE = <span className="text-ink-tertiary">—</span>;

interface KeyValueListProps {
  /** `false` (from `condition && item`) leaves an item out */
  items: (KeyValueItem | false | null | undefined | '')[];
  layout?: 'grid' | 'inline';
}

/**
 * Description list of facts. `grid` lays items out in responsive columns (label above value);
 * `inline` puts labels in a leading column, which suits narrow inspector panels.
 * Falsy entries in `items` are skipped, so conditional facts can be written inline.
 */
export function KeyValueList({ items, layout = 'grid' }: KeyValueListProps) {
  const visible = items.filter((item): item is KeyValueItem => Boolean(item));
  if (layout === 'inline') {
    return (
      <dl className="grid grid-cols-[minmax(7.5rem,max-content)_minmax(0,1fr)] gap-x-4 gap-y-2">
        {visible.map((item) => (
          <Fragment key={item.label}>
            <dt className="text-callout text-ink-secondary">{item.label}</dt>
            <dd className={cx('min-w-0 break-words text-callout text-ink', item.mono && 'font-mono')}>
              {item.value ?? EMPTY_VALUE}
            </dd>
          </Fragment>
        ))}
      </dl>
    );
  }
  return (
    <dl className="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-x-6 gap-y-4">
      {visible.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-caption text-ink-tertiary">{item.label}</dt>
          <dd className={cx('mt-0.5 break-words text-body text-ink', item.mono && 'font-mono text-callout')}>
            {item.value ?? EMPTY_VALUE}
          </dd>
        </div>
      ))}
    </dl>
  );
}

interface KeyValueItem {
  label: string;
  value?: ReactNode;
  mono?: boolean;
}
