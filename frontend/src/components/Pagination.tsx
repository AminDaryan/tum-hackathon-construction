import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { PressEvent } from 'react-aria-components';
import { focusSectionHeading } from '../utils/focus.ts';
import { formatCount } from '../utils/format.ts';
import { Button } from './Button.tsx';
import { t } from '../i18n/messages.ts';
import { cx } from '../utils/classNames.ts';

interface PaginationProps {
  offset: number;
  limit: number;
  total?: number;
  onChange: (offset: number) => void;
  itemLabel: string;
  className?: string;
  showEmpty?: boolean;
}

/**
 * Offset/limit pagination: the visible range with the total, and Previous/Next when there is
 * more than one page. Without items it renders nothing, unless `showEmpty` ("0 files").
 *
 * Changing the page moves focus to the heading of the enclosing {@link Section}: the list, and
 * often this pager, is replaced while the next page loads, so the clicked button would otherwise
 * drop focus to the page body. Keyboard users continue from the top of the new page.
 */
export function Pagination({
  offset,
  limit,
  total,
  onChange,
  itemLabel,
  className,
  showEmpty = false,
}: PaginationProps) {
  if (!total && !showEmpty) {
    return null;
  }
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + limit, total ?? 0);
  const hasPrevious = offset > 0;
  const hasNext = offset + limit < (total ?? 0);
  const goTo = (event: PressEvent, nextOffset: number) => {
    focusSectionHeading(event.target);
    onChange(nextOffset);
  };
  return (
    <nav
      aria-label={t('{items} pages', { items: itemLabel })}
      className={cx('flex flex-wrap items-center justify-between gap-3 border-t border-hairline px-4 py-2', className)}
    >
      <p className="text-callout tabular-nums text-ink-secondary">
        {total
          ? t('{start}–{end} of {total} {items}', { start: formatCount(start), end: formatCount(end), total: formatCount(total), items: itemLabel })
          : t('{total} {items}', { total: formatCount(0), items: itemLabel })}
      </p>
      {(hasPrevious || hasNext) && (
        <div className="flex items-center gap-2">
          <Button icon={ChevronLeft} isDisabled={!hasPrevious} onPress={(event) => goTo(event, Math.max(0, offset - limit))}>
            {t('Previous')}
          </Button>
          <Button icon={ChevronRight} iconPosition="end" isDisabled={!hasNext} onPress={(event) => goTo(event, offset + limit)}>
            {t('Next')}
          </Button>
        </div>
      )}
    </nav>
  );
}
