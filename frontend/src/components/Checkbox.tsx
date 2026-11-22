import { Check, Minus } from 'lucide-react';
import { Checkbox as AriaCheckbox } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { HIT_MIN_HEIGHT } from './hitTarget.ts';
import type { ReactNode } from 'react';

interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  indeterminate?: boolean;
  className?: string;
  children: ReactNode;
}

/** Checkbox with its label (React Aria): the whole row is the hit area. */
export function Checkbox({
  checked,
  onChange,
  disabled = false,
  indeterminate = false,
  className,
  children,
}: CheckboxProps) {
  return (
    <AriaCheckbox
      isSelected={checked}
      onChange={onChange}
      isDisabled={disabled}
      isIndeterminate={indeterminate}
      className={cx('group flex cursor-pointer items-center gap-2.5 text-callout text-ink data-disabled:opacity-50', HIT_MIN_HEIGHT, className)}
    >
      {({ isSelected, isIndeterminate }) => (
        <>
          <span
            aria-hidden="true"
            className={cx(
              'inline-flex size-4.5 shrink-0 items-center justify-center rounded-sm border transition-colors',
              'group-data-focus-visible:outline-2 group-data-focus-visible:outline-offset-2 group-data-focus-visible:outline-focus',
              isSelected || isIndeterminate ? 'border-accent bg-accent text-on-accent' : 'border-control-border bg-surface group-hover:border-ink-tertiary',
            )}
          >
            {isIndeterminate ? <Minus className="size-3.5" strokeWidth={3} /> : isSelected && <Check className="size-3.5" strokeWidth={3} />}
          </span>
          <span className="min-w-0">{children}</span>
        </>
      )}
    </AriaCheckbox>
  );
}
