import { cx } from '../utils/classNames.ts';
import { describeSource, formatCellReference } from '../utils/sourceLocation.ts';
import type { SourceLocation } from '../services/apiTypes.ts';

interface CellReferenceProps {
  source?: SourceLocation | null;
  className?: string;
}

/**
 * Source cell reference in monospace: `LV!C12`, `'Bill 1'!C12`, `record 14, field 3`.
 * The long form ("Sheet 'LV' cell C12") is available on hover.
 */
export function CellReference({ source, className }: CellReferenceProps) {
  const reference = formatCellReference(source);
  if (!reference) {
    return <span className="text-ink-tertiary">—</span>;
  }
  return (
    <span className={cx('font-mono text-callout text-ink', className)} title={describeSource(source) ?? undefined}>
      {reference}
    </span>
  );
}
