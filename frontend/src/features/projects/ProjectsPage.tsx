import { Plus } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, ButtonLink } from '../../components/Button.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { StatusSelect } from '../../components/StatusSelect.tsx';
import { TableCard, usePagedRows } from '../../components/TableCard.tsx';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { t } from '../../i18n/messages.ts';
import { getReviewerSession } from '../../services/collaborationService.ts';
import { listProjects, updateProject } from '../../services/projectsService.ts';
import { useSession } from '../../stores/useSession.ts';
import { formatDate } from '../../utils/format.ts';
import { ProjectAssigneesSelect } from './ProjectAssigneesSelect.tsx';
import { ProjectFilterBar } from './ProjectFilterBar.tsx';
import { filterProjects, NO_PROJECT_FILTERS, projectAssignees, type ProjectFilters } from './projectFilters.ts';
import { newestFirst } from './projectOverview.ts';
import { projectStatusOptions } from './projectStatus.ts';
import type { DataTableColumn } from '../../components/DataTable.tsx';
import type { Project } from '../../services/apiTypes.ts';

interface ProjectColumnsOptions {
  /** the person may change projects: the status and the assigned people are controls */
  editable: boolean;
  /** a change is being saved */
  saving: boolean;
  /** the people who can be assigned */
  people: readonly string[];
  onChange: (project: Project, changes: { status?: Project['status']; assignees?: string[] }) => void;
}

/** The columns of the projects table, in the UI language. */
function projectColumns({ editable, saving, people, onChange }: ProjectColumnsOptions): DataTableColumn<Project>[] {
  const statuses = projectStatusOptions();
  return [
    {
      key: 'name',
      placeholderWidth: 'w-48',
      header: t('Name'),
      className: 'min-w-48',
      render: (project) => (
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-ink">{project.name}</span>
          </span>
          {project.preparation !== 'ready' && (
            <span className="text-caption text-ink-secondary">
              {project.preparation === 'preparing' ? t('Preparing the demo files…') : t('The demo files could not be prepared')}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'description',
      placeholderWidth: 'w-80',
      header: t('projects.column.description'),
      headerClassName: 'max-md:hidden',
      className: 'max-md:hidden min-w-56',
      render: (project) => <span className="line-clamp-1 text-ink-secondary">{project.description || '—'}</span>,
    },
    {
      key: 'assignees',
      placeholderWidth: 'w-6',
      header: t('Assigned to'),
      headerClassName: 'max-lg:hidden',
      className: 'max-lg:hidden',
      render: (project) => (
        <ProjectAssigneesSelect
          projectName={project.name}
          value={project.assignees ?? []}
          people={people}
          onChange={(assignees) => onChange(project, { assignees })}
          readOnly={!editable}
          disabled={saving}
        />
      ),
    },
    {
      key: 'files',
      placeholderWidth: 'w-4',
      header: t('Files'),
      align: 'right',
      headerClassName: 'max-lg:hidden',
      className: 'max-lg:hidden tabular-nums',
      render: (project) => project.files.length,
    },
    {
      key: 'created',
      placeholderWidth: 'w-24',
      header: t('Created'),
      className: 'whitespace-nowrap text-ink-secondary tabular-nums',
      render: (project) => <time dateTime={project.created_at}>{formatDate(project.created_at)}</time>,
    },
    {
      key: 'status',
      placeholderWidth: 'w-24',
      header: t('Status'),
      render: (project) => (
        <StatusSelect
          label={t('Status of {name}', { name: project.name })}
          value={project.status ?? 'in_progress'}
          options={statuses}
          onChange={(status) => onChange(project, { status })}
          readOnly={!editable}
          disabled={saving}
        />
      ),
    },
  ];
}

/** Projects per page. */
const PAGE_SIZE = 10;

/**
 * All projects in one table, ten a page and as tall as its rows, newest first: name, short
 * description, assigned users, files, the day it was created and whether it is in progress or
 * finished. "Create project" sits at the top right of the table, the search and the filters
 * above its rows; a row opens the project. Those who may change projects pick the assigned
 * people and the status in the row itself; each change is saved at once.
 */
export function ProjectsPage() {
  useDocumentTitle(t('Projects'));
  const navigate = useNavigate();
  const { can } = useSession();
  const editable = can('write');
  const resource = useApiResource((signal) => listProjects(signal), []);
  const projects = useMemo(() => (Array.isArray(resource.data) ? newestFirst(resource.data) : null), [resource.data]);
  // The reviewers who joined can be assigned, as when a project is created.
  const session = useApiResource((signal) => getReviewerSession(signal), [], { enabled: editable });
  const people = [...(session.data?.reviewers ?? []).map((person) => person.name), ...projectAssignees(projects ?? [])];
  const change = useAsyncAction((signal, projectId: string, changes: { status?: Project['status']; assignees?: string[] }) =>
    updateProject(projectId, changes, signal),
  );
  const save = async (project: Project, changes: { status?: Project['status']; assignees?: string[] }) => {
    const saved = await change.execute(project.project_id, changes);
    if (saved) resource.setData((current) => current?.map((candidate) => (candidate.project_id === saved.project_id ? saved : candidate)));
  };
  const preparing = projects?.some((project) => project.preparation === 'preparing');
  const [filters, setFilters] = useState<ProjectFilters>(NO_PROJECT_FILTERS);
  const shown = projects ? filterProjects(projects, filters) : null;
  const page = usePagedRows(shown ?? [], PAGE_SIZE);
  const changeFilters = (next: ProjectFilters) => {
    setFilters(next);
    page.setOffset(0);
  };

  useEffect(() => {
    if (!preparing) return undefined;
    const timer = setInterval(resource.reload, 2000);
    return () => clearInterval(timer);
  }, [preparing, resource.reload]);

  if (resource.error && !projects) return <ErrorState error={resource.error} onRetry={resource.reload} />;

  const noMatch = Boolean(projects?.length) && shown?.length === 0;
  let status: string | null = null;
  if (projects && !projects.length) status = t('No projects yet');
  else if (noMatch) status = t('No projects match the search and filters');
  return (
    <div className="flex flex-col gap-4">
      {change.error && <ErrorState error={change.error} title={t('The changes could not be saved')} compact />}
      <TableCard
        title={t('All projects')}
        count={shown ? shown.length : null}
        actions={
          <ButtonLink to="/projects/new" variant="primary" icon={Plus}>
            {t('Create project')}
          </ButtonLink>
        }
        summary={<ProjectFilterBar filters={filters} onChange={changeFilters} assignees={projectAssignees(projects ?? [])} />}
        columns={projectColumns({ editable, saving: change.pending, people, onChange: save })}
        rows={page.rows}
        getRowKey={(project) => project.project_id}
        caption={t('Projects')}
        onRowActivate={(project) => navigate(`/projects/${encodeURIComponent(project.project_id)}`)}
        pageSize={PAGE_SIZE}
        fitRows
        offset={page.offset}
        total={page.total}
        onOffsetChange={page.setOffset}
        itemLabel={page.total === 1 ? t('project') : t('projects')}
        status={status}
        statusAction={noMatch && <Button onPress={() => changeFilters(NO_PROJECT_FILTERS)}>{t('Clear filters')}</Button>}
        loading={!projects}
        loadingLabel={t('Loading projects…')}
      />
    </div>
  );
}
