import { useId } from 'react';
import { cx } from '../utils/classNames.ts';
import type { ReactNode } from 'react';

interface SectionProps {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  surface?: boolean;
  padded?: boolean;
  className?: string;
  children?: ReactNode;
}

/**
 * A titled group of content. With `surface` (default) the content sits on one white work
 * surface with a hairline border; content inside must not add another bordered surface.
 */
export function Section({
  title,
  description,
  actions,
  surface = true,
  padded = false,
  className,
  children,
}: SectionProps) {
  const headingId = useId();
  return (
    <section aria-labelledby={title ? headingId : undefined} className={cx('mb-8 last:mb-0', className)}>
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            {title && (
              <h2 id={headingId} className="text-headline text-ink">
                {title}
              </h2>
            )}
            {description && <p className="mt-0.5 max-w-3xl text-callout text-ink-secondary">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {surface ? <div className={cx('surface', padded && 'p-4')}>{children}</div> : children}
    </section>
  );
}
