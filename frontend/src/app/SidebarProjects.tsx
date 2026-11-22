import { Folder, FolderOpen } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../i18n/useI18n.ts';
import { PROJECTS_ITEM, projectPath } from './navigation.ts';
import { SidebarGroup } from './SidebarGroup.tsx';
import { SidebarLink } from './SidebarLink.tsx';
import { sidebarItems } from './sidebarLists.ts';
import type { Project } from '../services/apiTypes.ts';
import type { SidebarList } from './useSidebarLists.ts';

interface SidebarProjectsProps {
  list: SidebarList<Project>;
  /** the project whose page is open */
  projectId: string | null;
}

/**
 * Projects in the navigation: the heading with a + that creates a project, the newest projects,
 * the open one among them (marked as the current page, with an open folder), and "More projects"
 * when some are left out. The open project's own pages are in the bar under the top bar.
 */
export function SidebarProjects({ list, projectId }: SidebarProjectsProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { shown, more } = sidebarItems(list.data ?? [], projectId, (project) => project.project_id);
  return (
    <SidebarGroup
      to={PROJECTS_ITEM.to}
      end={shown.some((project) => project.project_id === projectId)}
      label={t(PROJECTS_ITEM.labelKey)}
      icon={PROJECTS_ITEM.icon}
      addLabel={t('Create project')}
      onAdd={() => navigate('/projects/new')}
      more={more}
      moreLabel={t('More projects')}
      loading={list.data === undefined && list.loading}
    >
      {shown.map((project) => (
        <li key={project.project_id}>
          <SidebarLink
            to={projectPath(project.project_id)}
            label={project.name}
            icon={project.project_id === projectId ? FolderOpen : Folder}
            depth={1}
          />
        </li>
      ))}
    </SidebarGroup>
  );
}
