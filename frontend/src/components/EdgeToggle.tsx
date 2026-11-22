import type { ElementType } from 'react';
import { Button as AriaButton } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { HIT_SQUARE } from './hitTarget.ts';
import { Tooltip } from './Tooltip.tsx';

interface EdgeToggleProps {
  label: string;
  icon: ElementType;
  expanded: boolean;
  controls?: string;
  onPress: () => void;
  tooltipPlacement?: 'top' | 'bottom' | 'start' | 'end';
  className?: string;
}

/**
 * The arrow that collapses or expands a pane, in the middle of the pane's edge (`className`
 * places it on the edge, inside a positioned parent): a 24 px round button drawn in a 44 × 44 px
 * hit area (48 × 48 on coarse pointers), above its neighbours. `icon` points the way the pane
 * will go.
 */
export function EdgeToggle({
  label,
  icon: Icon,
  expanded,
  controls,
  onPress,
  tooltipPlacement = 'end',
  className,
}: EdgeToggleProps) {
  return (
    <Tooltip content={label} placement={tooltipPlacement}>
      <AriaButton
        aria-label={label}
        aria-expanded={expanded}
        aria-controls={controls}
        onPress={onPress}
        className={cx('group absolute top-1/2 z-40 flex -translate-y-1/2 cursor-pointer items-center justify-center rounded-full', HIT_SQUARE, className)}
      >
        <span
          aria-hidden="true"
          className="flex size-6 items-center justify-center rounded-full border border-hairline-strong bg-surface text-ink-secondary shadow-sm transition-colors group-hover:border-accent group-hover:text-accent-strong"
        >
          <Icon className="size-3.5" strokeWidth={2} />
        </span>
      </AriaButton>
    </Tooltip>
  );
}
