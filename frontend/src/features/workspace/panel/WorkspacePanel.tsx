import { forwardRef } from 'react';
import { Tabs } from '../../../components/Tabs.tsx';
import { t } from '../../../i18n/messages.ts';
import { cx } from '../../../utils/classNames.ts';
import type { CSSProperties, KeyboardEventHandler, ReactNode } from 'react';

interface WorkspacePanelProps {
  id?: string;
  tabs: ({
      id: string;
      label: string;
      count?: number | string;
      countTone?: 'danger';
    })[];
  selectedId: string;
  onSelect: (id: string) => void;
  onKeyDown?: KeyboardEventHandler<HTMLElement>;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}

/**
 * The workspace's side panel: one tab list on top (its three tabs fit the panel's narrowest
 * width, so it never scrolls; it would wrap) and the selected tab below, filling the rest of
 * the panel. Each tab scrolls its own content (`PanelScroll`), so a tab can pin a footer such
 * as the decision bar. The panel is the containing block of what its tabs position (the hidden
 * inputs of checkboxes, screen-reader text), so a long list in a tab can never make the page
 * itself scroll, which would narrow the page by a scroll bar and move the panel.
 */
export const WorkspacePanel = forwardRef<HTMLElement, WorkspacePanelProps>(function WorkspacePanel(
  { id, tabs, selectedId, onSelect, onKeyDown, className, style, children },
  ref,
) {
  return (
    <aside
      ref={ref}
      id={id}
      aria-label={t('Side panel')}
      onKeyDown={onKeyDown}
      style={style}
      className={cx('@container relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-hairline bg-surface', className)}
    >
      <Tabs
        tabs={tabs}
        selectedId={selectedId}
        onSelect={onSelect}
        label={t('Side panel')}
        className="flex min-h-0 flex-1 flex-col"
        listClassName="px-2 pt-1"
        panelClassName="flex min-h-0 flex-1 flex-col"
      >
        {children}
      </Tabs>
    </aside>
  );
});

interface PanelScrollProps {
  className?: string;
  children?: ReactNode;
}

/** The scrolling body of a panel tab, with the panel's 16 px margins. */
export const PanelScroll = forwardRef<HTMLDivElement, PanelScrollProps>(function PanelScroll({ className, children }, ref) {
  return (
    <div ref={ref} className={cx('relative min-h-0 flex-1 overflow-y-auto px-3 py-3', className)}>
      {children}
    </div>
  );
});
