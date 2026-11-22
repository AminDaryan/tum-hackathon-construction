import { cx } from '../utils/classNames.ts';
import { STATUS_VOCABULARY, statusMeta } from '../utils/vocabulary.ts';

const DOT_CLASSES = {
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
  neutral: 'bg-neutral',
  accent: 'bg-accent',
};

interface StatusBadgeProps {
  kind: keyof typeof STATUS_VOCABULARY;
  status?: string;
  wrap?: boolean;
  className?: string;
}

/**
 * Lifecycle status (document, extraction quality, run, detector, review, health) as a coloured
 * dot plus its text label. The label carries the meaning; the dot is decorative. The label stays
 * on one line unless `wrap` is set (for a narrow table column).
 */
export function StatusBadge({ kind, status, wrap = false, className }: StatusBadgeProps) {
  const meta = statusMeta(kind, status);
  return (
    <span className={cx('inline-flex items-center gap-1.5 text-callout text-ink', !wrap && 'whitespace-nowrap', className)}>
      <span aria-hidden="true" className={cx('size-2 shrink-0 rounded-full', DOT_CLASSES[meta.tone] ?? DOT_CLASSES.neutral)} />
      {meta.label}
    </span>
  );
}
