import { LoaderCircle } from 'lucide-react';
import { cx } from '../utils/classNames.ts';

interface SpinnerProps {
  size?: 'sm' | 'md';
  className?: string;
}

/**
 * Indeterminate progress indicator. Decorative: always pair it with a text label.
 */
export function Spinner({ size = 'md', className }: SpinnerProps) {
  return (
    <LoaderCircle
      aria-hidden="true"
      strokeWidth={2}
      className={cx('shrink-0 animate-spin', size === 'sm' ? 'size-4' : 'size-5', className)}
    />
  );
}
