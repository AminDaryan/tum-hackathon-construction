import { ChevronRight } from 'lucide-react';
import { Button as AriaButton, Disclosure as AriaDisclosure, DisclosurePanel } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { HIT_MIN_HEIGHT } from './hitTarget.ts';
import type { ReactNode } from 'react';

const TITLE_CLASSES = Object.freeze({
  headline: 'text-headline',
  callout: 'text-callout font-semibold',
  caption: 'text-caption font-medium text-ink-secondary',
});

interface DisclosureProps {
  title: ReactNode;
  children?: ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  size?: 'headline' | 'callout' | 'caption';
  tone?: 'ink' | 'accent';
  className?: string;
}

/**
 * A section whose body opens and closes under its title (React Aria Disclosure): a button with a
 * chevron and `aria-expanded`, the body hidden while closed. The body slides open and closed in
 * 200 ms (none with reduced motion). Controlled when `open` and `onOpenChange` are given.
 */
export function Disclosure({
  title,
  children,
  defaultOpen = false,
  open,
  onOpenChange,
  size = 'callout',
  tone = 'ink',
  className,
}: DisclosureProps) {
  return (
    <AriaDisclosure
      defaultExpanded={defaultOpen}
      isExpanded={open}
      onExpandedChange={onOpenChange}
      className={cx('group', className)}
    >
        <AriaButton
          slot="trigger"
          className={cx(
            '-ml-1 flex w-full cursor-pointer items-center gap-1 rounded-md px-1 text-left',
            tone === 'accent' ? 'text-accent-strong' : 'text-ink',
            TITLE_CLASSES[size],
            HIT_MIN_HEIGHT,
          )}
        >
          <ChevronRight
            aria-hidden="true"
            className="size-4 shrink-0 transition-transform duration-200 ease-standard group-data-expanded:rotate-90"
            strokeWidth={1.75}
          />
          {title}
        </AriaButton>
      {/* React Aria sets the panel's height while it opens and closes. The 4 px padding inside a
          negative margin keeps the focus rings of the body from being clipped; once closed
          (hidden) the panel drops both, so it covers no part of the title above it. */}
      <DisclosurePanel className="-m-1 h-(--disclosure-panel-height) overflow-clip p-1 transition-[height] duration-200 ease-standard [&[hidden]]:m-0 [&[hidden]]:p-0">
        <div className="space-y-3 pt-2">{children}</div>
      </DisclosurePanel>
    </AriaDisclosure>
  );
}
