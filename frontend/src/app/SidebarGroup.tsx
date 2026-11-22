import { Ellipsis, Plus } from 'lucide-react';
import { IconButton } from '../components/IconButton.tsx';
import { Skeleton } from '../components/Skeleton.tsx';
import { cx } from '../utils/classNames.ts';
import { SidebarLink } from './SidebarLink.tsx';
import type { ElementType, ReactNode } from 'react';

/** Grey rows while the list loads. */
const LOADING_ROWS = ['w-28', 'w-20', 'w-24'];

interface SidebarGroupProps {
  /** the section's own page (all projects, all users) */
  to: string;
  label: string;
  icon: ElementType;
  /** The heading is current only on the section's own page: a row under it marks the open item. */
  end: boolean;
  /** the name of the + at the end of the heading's row, and what it does */
  addLabel: string;
  onAdd: () => void;
  /** the rows under the heading */
  children?: ReactNode;
  /** some are left out: a last row leads to the section's page */
  more: boolean;
  moreLabel: string;
  /** the list is loading: grey rows under the rows given */
  loading: boolean;
}

/**
 * A section of the navigation with a few of its items under it: the heading (a link to the
 * section's page) with a + at the end of its row, the rows, and "More …" when some are left out.
 */
export function SidebarGroup({ to, label, icon, end, addLabel, onAdd, children, more, moreLabel, loading }: SidebarGroupProps) {
  return (
    <li>
      <SidebarLink to={to} end={end} label={label} icon={icon} trailing={<IconButton icon={Plus} label={addLabel} onPress={onAdd} />} />
      <ul className="mt-1 flex flex-col gap-1 empty:hidden">
        {children}
        {loading &&
          LOADING_ROWS.map((width) => (
            <li key={width} aria-hidden="true" className="flex min-h-8 items-center gap-3 pl-8 pr-3 pointer-coarse:min-h-12">
              <Skeleton className="size-4 shrink-0" />
              <Skeleton className={cx('h-3', width)} />
            </li>
          ))}
        {more && (
          <li>
            <SidebarLink to={to} label={moreLabel} icon={Ellipsis} depth={1} marksCurrent={false} />
          </li>
        )}
      </ul>
    </li>
  );
}
