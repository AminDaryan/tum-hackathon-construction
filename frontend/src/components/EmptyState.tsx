import { Inbox } from 'lucide-react';
import { cx } from '../utils/classNames.ts';
import type { ElementType, ReactNode } from 'react';

interface EmptyStateProps {
  icon?: ElementType;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  headingLevel?: 2 | 3 | 4;
}

/**
 * Explains why there is nothing to show and, when possible, offers the real next step.
 */
export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  compact = false,
  headingLevel = 2,
}: EmptyStateProps) {
  const Heading = `h${headingLevel}` as const;
  return (
    <div className={cx('flex flex-col items-center text-center', compact ? 'px-4 py-8' : 'px-6 py-16')}>
      <span className="mb-3 inline-flex size-10 items-center justify-center rounded-full border border-hairline bg-surface-muted text-ink-tertiary">
        <Icon aria-hidden="true" className="size-5" strokeWidth={1.75} />
      </span>
      <Heading className="text-headline text-ink">{title}</Heading>
      {description && <div className="mt-1 max-w-md text-body text-ink-secondary">{description}</div>}
      {action && <div className="mt-4 flex flex-wrap items-center justify-center gap-2">{action}</div>}
    </div>
  );
}
