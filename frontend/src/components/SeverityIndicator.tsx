import { cx } from '../utils/classNames.ts';
import { humanize, SEVERITY_META } from '../utils/vocabulary.ts';
import { t } from '../i18n/messages.ts';

const BAR_HEIGHTS = ['h-[4px]', 'h-[7px]', 'h-[10px]', 'h-[13px]'];

interface SeverityIndicatorProps {
  severity: string;
  hideLabel?: boolean;
}

/**
 * Severity as text plus a small graded bar indicator (info = no bars ... critical = four bars).
 * Severity is neutral ink on purpose: colour belongs to the evidence class.
 */
export function SeverityIndicator({ severity, hideLabel = false }: SeverityIndicatorProps) {
  const meta = SEVERITY_META[severity] ?? { label: humanize(severity), rank: 0 };
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span aria-hidden="true" className="inline-flex h-[13px] items-end gap-px">
        {BAR_HEIGHTS.map((height, index) => (
          <span
            key={height}
            className={cx('w-[3px] rounded-[1px]', height, index < meta.rank ? 'bg-ink' : 'bg-hairline-strong')}
          />
        ))}
      </span>
      <span className={cx('text-callout text-ink', hideLabel && 'sr-only')}>{t(meta.label)}</span>
    </span>
  );
}
