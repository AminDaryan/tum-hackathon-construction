import { Link, NavLink } from 'react-router-dom';
import { HIT_TARGET } from '../components/hitTarget.ts';
import { cx } from '../utils/classNames.ts';
import type { ElementType, ReactNode } from 'react';

/** The room before the icon at each level: a section, a project or user under it. */
const INDENT = ['pl-4 pr-3', 'pl-8 pr-3'] as const;

const LINK = cx('group relative flex min-w-0 flex-1 items-center gap-3 rounded-md text-callout font-medium', HIT_TARGET);

interface SidebarLinkProps {
  to: string;
  label: string;
  icon: ElementType;
  /** 0 a section, 1 a project or user under it */
  depth?: 0 | 1;
  /** current only on this very address, not below it */
  end?: boolean;
  /** Off for "More …", which leads to a page the section's own row marks. */
  marksCurrent?: boolean;
  /** a control at the end of the row (the + of a section), inside the row's highlight */
  trailing?: ReactNode;
}

/**
 * One row of the navigation: an icon and a name, indented by its level, and `trailing` at its
 * end. The whole row is highlighted on hover, `trailing` included. The current page is in Ink on
 * the selected state with a 3 px accent bar on its leading edge.
 */
export function SidebarLink({ to, label, icon: Icon, depth = 0, end, marksCurrent = true, trailing = null }: SidebarLinkProps) {
  const content = (
    <>
      <Icon aria-hidden="true" className="size-4 shrink-0 group-aria-[current=page]:text-accent" strokeWidth={1.75} />
      <span className="truncate">{label}</span>
    </>
  );
  return (
    <div className="state-layer flex items-center rounded-md text-ink-secondary transition-colors hover:text-ink has-[[aria-current=page]]:bg-state-selected has-[[aria-current=page]]:text-ink">
      {marksCurrent ? (
        <NavLink
          to={to}
          end={end}
          title={label}
          className={cx(
            LINK,
            INDENT[depth],
            'aria-[current=page]:after:absolute aria-[current=page]:after:inset-y-2 aria-[current=page]:after:left-0 aria-[current=page]:after:w-[3px] aria-[current=page]:after:rounded-full aria-[current=page]:after:bg-accent',
          )}
        >
          {content}
        </NavLink>
      ) : (
        <Link to={to} title={label} className={cx(LINK, INDENT[depth])}>
          {content}
        </Link>
      )}
      {trailing}
    </div>
  );
}
