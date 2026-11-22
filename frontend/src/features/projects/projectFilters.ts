/** The search and filters over the projects table, without React. */
import { matchesSearch } from '../../utils/textSearch.ts';
import type { Project } from '../../services/apiTypes.ts';

export interface ProjectFilters {
  /** words found in the name, the description or an assigned user */
  search: string;
  /** '' for every status */
  status: '' | Project['status'];
  /** an assigned user's name; '' for everyone */
  assignee: string;
}

export const NO_PROJECT_FILTERS: Readonly<ProjectFilters> = Object.freeze({ search: '', status: '', assignee: '' });

/** The projects that meet every filter, in their order. A project without a status is in progress. */
export function filterProjects(projects: readonly Project[], filters: ProjectFilters): Project[] {
  return projects.filter(
    (project) =>
      (!filters.status || (project.status ?? 'in_progress') === filters.status) &&
      (!filters.assignee || (project.assignees ?? []).includes(filters.assignee)) &&
      matchesSearch(filters.search, [project.name, project.description, ...(project.assignees ?? [])]),
  );
}

/** Every user assigned to at least one project, once each, in alphabetical order. */
export function projectAssignees(projects: readonly Project[]): string[] {
  const names = new Set(projects.flatMap((project) => project.assignees ?? []));
  return [...names].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
}
