import { cx } from '../utils/classNames.ts';
import { formatDateTime } from '../utils/format.ts';

interface TimestampProps {
  value?: string | null;
  className?: string;
}

/**
 * A point in time in the reader's locale; the exact ISO value is kept in `dateTime` and shown
 * on hover.
 */
export function Timestamp({ value, className }: TimestampProps) {
  if (!value) {
    return <span className="text-ink-tertiary">—</span>;
  }
  return (
    <time dateTime={value} title={value} className={cx('tabular-nums', className)}>
      {formatDateTime(value)}
    </time>
  );
}
