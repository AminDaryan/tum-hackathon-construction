/**
 * Top-level sections, in the order of the navigation (Projects, then Users for administrators),
 * with Settings, which the user menu opens over the page (see SettingsDialog), and the pages of
 * one project, listed under the open project in Projects. Files are opened in the project's
 * Workspace; everything about one file (its sheet, the checks, the issues and the exports) lives
 * there.
 */
import { Building2, FileChartColumn, LayoutDashboard, ListChecks, PanelsTopLeft, Settings, Users, type LucideIcon } from 'lucide-react';
import type { Permission } from '../stores/sessionContext.ts';

interface NavSection {
  to: string;
  label: string;
  labelKey: string;
  /** the subtitle in the top bar */
  hintKey?: string;
  icon: LucideIcon;
  /** the section is listed only for those who have it */
  permission?: Permission;
}

/** A page of a project: the path after `/projects/:id`. */
export type ProjectPage = '' | 'workspace' | 'follow-ups' | 'reports' | 'edit';

export const PROJECTS_ITEM: Readonly<NavSection> = Object.freeze({ to: '/projects', label: 'Projects', labelKey: 'nav.projects', icon: Building2 });
export const USERS_ITEM: Readonly<NavSection> = Object.freeze({
  to: '/users',
  label: 'Users',
  labelKey: 'nav.users',
  icon: Users,
  permission: 'manage_users',
});

export const NAV_ITEMS: readonly NavSection[] = Object.freeze([PROJECTS_ITEM, USERS_ITEM]);

/** Settings, opened from the user menu; its old address still leads to it. */
export const SETTINGS_ITEM: Readonly<NavSection> = Object.freeze({ to: '/settings', label: 'Settings', labelKey: 'nav.settings', icon: Settings });

/** The pages of one project, under it in the navigation: `page` is the path after `/projects/:id`. */
export const PROJECT_NAV_ITEMS: readonly { page: ProjectPage; labelKey: string; icon: LucideIcon }[] = Object.freeze([
  { page: '', labelKey: 'project.nav.overview', icon: LayoutDashboard },
  { page: 'workspace', labelKey: 'project.nav.workspace', icon: PanelsTopLeft },
  { page: 'follow-ups', labelKey: 'project.nav.followUps', icon: ListChecks },
  { page: 'reports', labelKey: 'project.nav.reports', icon: FileChartColumn },
]);

/**
 * The address of a page of a project, with a search (`{ document, run, tab, ... }`; empty values
 * are left out).
 */
export function projectPath(
  projectId: string,
  page: ProjectPage = '',
  search: Record<string, string | null | undefined> | URLSearchParams = {},
): string {
  const base = `/projects/${encodeURIComponent(projectId)}${page ? `/${page}` : ''}`;
  const query = new URLSearchParams();
  const entries = search instanceof URLSearchParams ? search.entries() : Object.entries(search);
  for (const [key, value] of entries) if (value) query.set(key, value);
  const text = query.toString();
  return text ? `${base}?${text}` : base;
}

/**
 * The section a path belongs to (for the top bar), or null for an unknown one. The root is
 * Projects, where it leads, so the frame shown while the app starts names no missing page.
 */
export function sectionOf(pathname: string) {
  const first = `/${pathname.split('/')[1] || 'projects'}`;
  return [...NAV_ITEMS, SETTINGS_ITEM].find((item) => item.to === first) ?? null;
}

/**
 * Link to the workspace with a tab, a validation run and an issue chosen. These are the search
 * parameters the workspace reads: `tab`, `run` and `issue`.
 */
export function workspacePath({
  tab,
  runId,
  issueId,
}: {
  tab?: 'properties' | 'requirements' | 'issues' | 'report' | 'export' | null;
  runId?: string | null;
  issueId?: string | null;
} = {}): string {
  const params = new URLSearchParams();
  if (tab) params.set('tab', tab);
  if (runId) params.set('run', runId);
  if (issueId) params.set('issue', issueId);
  const search = params.toString();
  return search ? `/workspace?${search}` : '/workspace';
}
