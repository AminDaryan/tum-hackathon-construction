import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { NO_FILE_FILTERS, type FileFilters } from './projectFileFilters.ts';
import { projectPath } from '../../app/navigation.ts';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { ApiError } from '../../services/apiClient.ts';
import { getProject } from '../../services/projectsService.ts';
import { useWorkspace } from '../../stores/useWorkspace.ts';
import type { Project, ProjectDetail } from '../../services/apiTypes.ts';
import type { ReactNode } from 'react';

export interface ProjectContextValue {
  projectId: string;
  /** the whole detail, or null while it loads */
  loaded: ProjectDetail | null;
  project: Project | null;
  error: Error | null;
  /** the server has no project of this id */
  notFound: boolean;
  reload: () => void;
  overviewRiskPaging: { key: string; offset: number };
  setOverviewRiskPaging: (paging: { key: string; offset: number }) => void;
  overviewFollowUpOffset: number;
  setOverviewFollowUpOffset: (offset: number) => void;
  overviewFileFilters: FileFilters;
  setOverviewFileFilters: (filters: FileFilters) => void;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

interface ProjectProviderProps {
  projectId: string;
  children?: ReactNode;
}

/**
 * Loads one project (`GET /projects/{id}`: the project, its documents and the review counts of
 * its last validation) once for the project's navigation and all its pages. `loaded` is the
 * detail of this project only, never a previous one's.
 */
export function ProjectProvider({ projectId, children }: ProjectProviderProps) {
  // Keep the Overview's list choices while its rows are open in the Workspace.
  const [overviewRiskPaging, setOverviewRiskPaging] = useState({ key: '', offset: 0 });
  const [overviewFollowUpOffset, setOverviewFollowUpOffset] = useState(0);
  const [overviewFileFilters, setOverviewFileFilters] = useState<FileFilters>(NO_FILE_FILTERS);
  const resource = useApiResource((signal) => getProject(projectId, signal), [projectId]);
  const loaded = resource.data?.project?.project_id === projectId ? resource.data : null;
  const notFound = resource.error instanceof ApiError && resource.error.status === 404;
  const value = useMemo<ProjectContextValue>(
    () => ({
      projectId, loaded, project: loaded?.project ?? null, error: resource.error, notFound, reload: resource.reload,
      overviewRiskPaging, setOverviewRiskPaging, overviewFollowUpOffset, setOverviewFollowUpOffset,
      overviewFileFilters, setOverviewFileFilters,
    }),
    [projectId, loaded, resource.error, notFound, resource.reload, overviewRiskPaging, overviewFollowUpOffset, overviewFileFilters],
  );
  return <ProjectContext value={value}>{children}</ProjectContext>;
}

/**
 * The project of the page: `{ projectId, loaded, project, error, notFound, reload }`, where `loaded` is the
 * whole detail (`{ project, documents, review_counts }`) or null while it loads.
 */
export function useProject(): ProjectContextValue {
  const value = useContext(ProjectContext);
  if (!value) throw new Error('useProject must be used inside a ProjectProvider');
  return value;
}

/**
 * Opens a file of this project in its Workspace: `search` adds where to land (`run`, `tab`,
 * `risk`, `status`, `issue`).
 */
/** Opens a file of the project in its Workspace, with more of the Workspace's search parameters. */
export type OpenFile = (documentId: string, search?: Record<string, string | null | undefined>) => void;

export function useOpenFile(): OpenFile {
  const { projectId } = useProject();
  const { setActiveDocumentId } = useWorkspace();
  const navigate = useNavigate();
  return useCallback(
    (documentId, search = {}) => {
      setActiveDocumentId(documentId);
      navigate(projectPath(projectId, 'workspace', { document: documentId, ...search }));
    },
    [navigate, projectId, setActiveDocumentId],
  );
}
