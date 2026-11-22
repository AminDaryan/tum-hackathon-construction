import { NavLink } from 'react-router-dom';
import { tabLook } from '../components/Tabs.tsx';
import { useI18n } from '../i18n/useI18n.ts';
import { cx } from '../utils/classNames.ts';
import { PROJECT_NAV_ITEMS, projectPath } from './navigation.ts';

interface ProjectNavProps {
  projectId: string;
}

/**
 * The bar under the top bar on every page of one project: its pages (Overview, Workspace,
 * Follow-ups, Reports) from the left, as links that look like tabs, the current one underlined.
 * It is 48 px tall; pages that do not fit wrap onto a second line.
 */
export function ProjectNav({ projectId }: ProjectNavProps) {
  const { t } = useI18n();
  return (
    <div className="flex shrink-0 border-b border-hairline bg-surface px-6 max-sm:px-4">
      <nav aria-label={t('project.nav.label')} className="flex min-w-0">
        <ul className="-mx-3 flex flex-wrap gap-x-1">
          {PROJECT_NAV_ITEMS.map(({ page, labelKey, icon: Icon }) => (
            <li key={page} className="flex min-h-12">
              <NavLink
                to={projectPath(projectId, page)}
                end={page === ''}
                className={({ isActive }) => cx(tabLook(isActive), 'gap-2 focus-visible:-outline-offset-2')}
              >
                <Icon aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />
                {t(labelKey)}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
