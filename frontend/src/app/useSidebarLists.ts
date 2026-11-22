import { useEffect, useMemo } from 'react';
import { newestFirst } from '../features/projects/projectOverview.ts';
import { useApiResource } from '../hooks/useApiResource.ts';
import { listProjects } from '../services/projectsService.ts';
import { listUsers } from '../services/usersService.ts';
import { onSidebarListsRefresh } from './sidebarLists.ts';
import type { Project, UserAccount } from '../services/apiTypes.ts';

/** A list the navigation shows: `loading` also while it is read again, with the last one kept in `data`. */
export interface SidebarList<T> {
  data: T[] | undefined;
  error: Error | null;
  loading: boolean;
}

/**
 * The projects (newest first) and the user accounts (by name, as the server sorts them) the
 * navigation lists, read again on each refreshSidebarLists(). The accounts are read only with
 * `readUsers`, and count as loading until then.
 */
export function useSidebarLists({ readUsers }: { readUsers: boolean }): {
  projects: SidebarList<Project>;
  users: SidebarList<UserAccount>;
} {
  const projects = useApiResource((signal) => listProjects(signal), []);
  const users = useApiResource((signal) => listUsers(signal), [], { enabled: readUsers });
  const { reload: reloadProjects } = projects;
  const { reload: reloadUsers } = users;
  useEffect(
    () =>
      onSidebarListsRefresh(() => {
        reloadProjects();
        reloadUsers();
      }),
    [reloadProjects, reloadUsers],
  );
  const sortedProjects = useMemo(() => (projects.data ? newestFirst(projects.data) : undefined), [projects.data]);
  return {
    projects: { data: sortedProjects, error: projects.error, loading: projects.loading },
    users: { data: users.data, error: users.error, loading: !readUsers || users.loading },
  };
}
