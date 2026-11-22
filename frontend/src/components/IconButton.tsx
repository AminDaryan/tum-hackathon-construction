import { Button as AriaButton, type ButtonProps as AriaButtonProps } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { HIT_SQUARE } from './hitTarget.ts';
import { Tooltip } from './Tooltip.tsx';
import type { ElementType } from 'react';

const VARIANT_CLASSES = {
  ghost: 'text-ink-secondary hover:text-ink',
  outlined: 'border border-hairline-strong bg-surface text-ink shadow-control hover:border-control-border',
};

interface IconButtonProps extends Omit<AriaButtonProps, 'className' | 'children'> {
  icon: ElementType;
  label: string;
  variant?: 'ghost' | 'outlined';
  className?: string;
}

/**
 * Square icon-only button: 32 × 32 px, 48 × 48 on coarse pointers. `label` is required: it is the
 * accessible name and the tooltip that appears on hover and keyboard focus.
 */
export function IconButton({ icon: Icon, label, variant = 'ghost', className, ...rest }: IconButtonProps) {
  return (
    <Tooltip content={label}>
      <AriaButton
        aria-label={label}
        className={cx(
          'state-layer inline-flex shrink-0 cursor-pointer items-center justify-center rounded-md transition-colors data-disabled:cursor-not-allowed data-disabled:opacity-50',
          HIT_SQUARE,
          VARIANT_CLASSES[variant],
          className,
        )}
        {...rest}
      >
        <Icon aria-hidden="true" className="size-4" strokeWidth={1.75} />
      </AriaButton>
    </Tooltip>
  );
}
