import { CircleAlert, Info } from 'lucide-react';
import { cx } from '../utils/classNames.ts';
import type { ReactNode } from 'react';

const TONES = {
  info: { icon: Info, container: 'border-context-border bg-context-bg', iconClassName: 'text-context' },
  danger: { icon: CircleAlert, container: 'border-violation-border bg-danger-bg', iconClassName: 'text-danger' },
};

interface BannerProps {
  tone?: keyof typeof TONES;
  title: string;
  children?: ReactNode;
  className?: string;
}

/**
 * Page-level notice, e.g. "Extraction failed". Icon and title always accompany the tone.
 */
export function Banner({ tone = 'info', title, children, className }: BannerProps) {
  const style = TONES[tone];
  const Icon = style.icon;
  return (
    <div className={cx('flex items-start gap-3 rounded-lg border px-4 py-3', style.container, className)}>
      <Icon aria-hidden="true" className={cx('mt-px size-5 shrink-0', style.iconClassName)} strokeWidth={1.75} />
      <div className="min-w-0 flex-1">
        <p className="text-headline text-ink">{title}</p>
        {children && <div className="mt-1 text-body text-ink-secondary">{children}</div>}
      </div>
    </div>
  );
}
