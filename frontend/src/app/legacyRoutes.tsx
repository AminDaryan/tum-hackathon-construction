/**
 * Addresses of the pages that were folded into the workspace (/workspace itself, /documents,
 * /runs, /issues, /exports and their detail pages). Bookmarks, notifications and older links
 * still use them; each one opens the file in its project's Workspace at the matching place.
 */
import { useEffect } from 'react';
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useApiResource } from '../hooks/useApiResource.ts';
import { DocumentPlaceholder } from '../features/workspace/DocumentView.tsx';
import { t } from '../i18n/messages.ts';
import { listProjects } from '../services/projectsService.ts';
import { useWorkspace } from '../stores/useWorkspace.ts';
import { projectPath, workspacePath } from './navigation.ts';

/**
 * /workspace: the Workspace of a project. With `project`, that project's, keeping the rest of the
 * search; otherwise the file (`document`, or the one open before) in the Workspace of the first
 * project that holds it. Without either, or when no project holds the file: Projects.
 */
export function WorkspaceRedirect() {
  const [params] = useSearchParams();
  const { activeDocumentId } = useWorkspace();
  const projectId = params.get('project');
  const documentId = params.get('document') || activeDocumentId;
  const lookup = useApiResource((signal) => listProjects(signal), [], { enabled: !projectId && Boolean(documentId) });
  const search = new URLSearchParams(params);
  search.delete('project');
  if (documentId) search.set('document', documentId);

  if (projectId) return <Navigate to={projectPath(projectId, 'workspace', search)} replace />;
  if (!documentId || lookup.error) return <Navigate to="/projects" replace />;
  if (!lookup.data) return <DocumentPlaceholder label={t('Opening the file…')} />;
  const holder = lookup.data.find((project) => project.files?.some((file) => file.document_id === documentId));
  return <Navigate to={holder ? projectPath(holder.project_id, 'workspace', search) : '/projects'} replace />;
}

/** /documents/:documentId: makes that document the open file, then shows the workspace. */
export function OpenDocumentRoute() {
  const { documentId } = useParams();
  const { setActiveDocumentId } = useWorkspace();
  const navigate = useNavigate();

  useEffect(() => {
    setActiveDocumentId(documentId ?? null);
    navigate('/workspace', { replace: true });
  }, [documentId, setActiveDocumentId, navigate]);

  return null;
}

interface LegacyRedirectProps {
  tab: 'requirements' | 'issues' | 'export';
}

/**
 * /runs, /runs/:runId, /issues, /issues/:issueId and /exports: the workspace with the tab that
 * replaced the page. The run comes from the path or from an existing `run` query parameter.
 */
export function LegacyRedirect({ tab }: LegacyRedirectProps) {
  const { runId, issueId } = useParams();
  const [searchParams] = useSearchParams();
  const target = workspacePath({ tab, runId: runId ?? searchParams.get('run'), issueId });
  return <Navigate to={target} replace />;
}
