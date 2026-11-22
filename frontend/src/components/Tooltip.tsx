import { Tooltip as AriaTooltip, TooltipTrigger } from 'react-aria-components';
import type { ReactElement, ReactNode } from 'react';

interface TooltipProps {
  content: ReactNode;
  children: ReactElement;
  placement?: 'top' | 'bottom' | 'start' | 'end';
}

/**
 * Accessible tooltip (WCAG 1.4.13), built on React Aria: opens on hover after 400 ms and at once
 * on keyboard focus, closes on Escape, blur and pointer leave, fades in and out, and is linked to
 * the trigger through aria-describedby. It renders in a portal, so scroll containers never clip it.
 *
 * `children` is the trigger, a React Aria button.
 */
export function Tooltip({ content, children, placement = 'top' }: TooltipProps) {
  return (
    <TooltipTrigger delay={400} closeDelay={100}>
      {children}
      <AriaTooltip
        offset={6}
        placement={placement}
        className="z-50 max-w-72 origin-(--trigger-anchor-point) rounded-md bg-ink px-2.5 py-1.5 text-left text-caption font-normal text-surface shadow-popover data-entering:animate-[popover-in_150ms_var(--ease-standard)] data-exiting:animate-[popover-out_120ms_var(--ease-standard)_forwards]"
      >
        {content}
      </AriaTooltip>
    </TooltipTrigger>
  );
}
