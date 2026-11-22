import { useEffect, useRef } from 'react';
import { Tab, TabList, TabPanel, Tabs as AriaTabs } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { fadeIn } from '../utils/motion.ts';
import { HIT_TARGET } from './hitTarget.ts';
import type { ReactNode } from 'react';

/**
 * The look of a tab: its label on the tab row's line, the chosen one in Ink with the accent
 * underline, which grows under it as it shrinks away under the one left. Shared with links that
 * stand as tabs (the pages of a project).
 */
export function tabLook(selected: boolean) {
  return cx(
    'state-layer relative inline-flex shrink-0 cursor-pointer items-center whitespace-nowrap rounded-t-md px-3 text-callout font-medium transition-colors',
    HIT_TARGET,
    'after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-accent after:transition-transform after:duration-200 after:ease-standard',
    selected ? 'text-ink after:scale-x-100' : 'text-ink-secondary after:scale-x-0 hover:text-ink',
  );
}

function tabClassName({ isSelected }: { isSelected: boolean }) {
  return cx(
    tabLook(isSelected),
    'outline-none data-focus-visible:outline-2 data-focus-visible:-outline-offset-2 data-focus-visible:outline-focus',
  );
}

interface TabCountProps {
  count: number | string;
  tone?: 'danger';
}

/** The count after a tab label; `danger` draws a red pill (findings that need attention). */
function TabCount({ count, tone }: TabCountProps) {
  return tone === 'danger' ? (
    <span className="ml-1.5 inline-flex min-w-5 justify-center rounded-full bg-violation px-1.5 text-caption font-semibold tabular-nums text-on-accent">
      {count}
    </span>
  ) : (
    <span className="ml-1.5 tabular-nums text-ink-tertiary">{count}</span>
  );
}

interface TabsProps {
  tabs: ({
      id: string;
      label: string;
      count?: number | string;
      countTone?: 'danger';
    })[];
  selectedId?: string;
  onSelect: (id: string) => void;
  label: string;
  children?: ReactNode;
  className?: string;
  listClassName?: string;
  panelClassName?: string;
  trailing?: ReactNode;
}

/**
 * WAI-ARIA tabs (React Aria) with automatic activation: Arrow Left/Right move between tabs and
 * select them, Home/End jump to the first/last tab. Only the selected tab is in the Tab sequence.
 * The list never scrolls: tabs that do not fit wrap onto a second line.
 * The caller renders the selected tab's content as `children`; it fades in when the tab changes,
 * and the underline grows under the new tab. A tab's `count` shows after its label;
 * `countTone: 'danger'` draws it as a red pill. `trailing` (the page's actions) sits at
 * the end of the tab row; where the row is too narrow it moves above the tabs, so the tabs stay
 * on the row's line.
 */
export function Tabs({
  tabs,
  selectedId,
  onSelect,
  label,
  children,
  className,
  listClassName,
  panelClassName,
  trailing,
}: TabsProps) {
  const selectedKey = tabs.some((tab) => tab.id === selectedId) ? selectedId : tabs[0]?.id;
  const panelRef = useRef<HTMLDivElement>(null);
  const shownKey = useRef(selectedKey);

  useEffect(() => {
    if (shownKey.current === selectedKey) return;
    shownKey.current = selectedKey;
    fadeIn(panelRef.current);
  }, [selectedKey]);

  const list = (
    <TabList aria-label={label} className={cx('flex shrink-0 flex-wrap gap-1', !trailing && 'border-b border-hairline', listClassName)}>
      {tabs.map((tab) => (
        <Tab key={tab.id} id={tab.id} className={tabClassName}>
          {tab.label}
          {tab.count !== undefined && <TabCount count={tab.count} tone={tab.countTone} />}
        </Tab>
      ))}
    </TabList>
  );

  return (
    <AriaTabs selectedKey={selectedKey} onSelectionChange={(key) => onSelect(String(key))} className={className}>
      {trailing ? (
        <div className="flex flex-wrap-reverse items-end justify-between gap-x-6 gap-y-2 border-b border-hairline">
          {list}
          <div className="flex flex-wrap items-center gap-2 pb-2">{trailing}</div>
        </div>
      ) : (
        list
      )}
      <TabPanel
        ref={panelRef}
        id={selectedKey}
        className={cx(
          panelClassName ?? 'pt-4',
          'outline-none data-focus-visible:outline-2 data-focus-visible:outline-offset-4 data-focus-visible:outline-focus',
        )}
      >
        {children}
      </TabPanel>
    </AriaTabs>
  );
}
