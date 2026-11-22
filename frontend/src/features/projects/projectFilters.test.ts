import { describe, expect, it } from 'vitest';
import { filterProjects, NO_PROJECT_FILTERS, projectAssignees } from './projectFilters.ts';
import type { Project } from '../../services/apiTypes.ts';

function project(project_id: string, overrides: Partial<Project> = {}): Project {
  return {
    project_id,
    name: project_id,
    description: '',
    created_at: '2026-11-21T10:00:00Z',
    status: 'in_progress',
    assignees: [],
    decision_cutoff: null,
    files: [],
    demo_key: null,
    preparation: 'ready',
    preparation_error: null,
    validation: null,
    ...overrides,
  };
}

const PROJECTS = [
  project('riverside', { name: 'Riverside', description: 'Bridge works', assignees: ['Larissa', 'Amin'] }),
  project('school', { name: 'School', status: 'finished', assignees: ['amin'] }),
  project('depot', { name: 'Depot', status: undefined as unknown as Project['status'] }),
];
const ids = (projects: Project[]) => projects.map((item) => item.project_id);

describe('filterProjects', () => {
  it('keeps every project without filters', () => {
    expect(ids(filterProjects(PROJECTS, NO_PROJECT_FILTERS))).toEqual(['riverside', 'school', 'depot']);
  });

  it('searches the name, the description and the assigned users', () => {
    expect(ids(filterProjects(PROJECTS, { ...NO_PROJECT_FILTERS, search: 'bridge' }))).toEqual(['riverside']);
    expect(ids(filterProjects(PROJECTS, { ...NO_PROJECT_FILTERS, search: 'AMIN' }))).toEqual(['riverside', 'school']);
  });

  it('filters by status, a project without one being in progress, and by an assigned user', () => {
    expect(ids(filterProjects(PROJECTS, { ...NO_PROJECT_FILTERS, status: 'in_progress' }))).toEqual(['riverside', 'depot']);
    expect(ids(filterProjects(PROJECTS, { ...NO_PROJECT_FILTERS, status: 'finished' }))).toEqual(['school']);
    expect(ids(filterProjects(PROJECTS, { ...NO_PROJECT_FILTERS, assignee: 'Amin' }))).toEqual(['riverside']);
    expect(ids(filterProjects(PROJECTS, { search: 'school', status: 'in_progress', assignee: '' }))).toEqual([]);
  });
});

describe('projectAssignees', () => {
  it('lists each assigned user once, alphabetically', () => {
    expect(projectAssignees(PROJECTS)).toEqual(['Amin', 'amin', 'Larissa']);
  });
});
