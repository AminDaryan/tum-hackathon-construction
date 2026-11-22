import { Check } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { ErrorState } from '../../components/ErrorState.tsx';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { usePageTitle } from '../../app/pageTitle.tsx';
import { t } from '../../i18n/messages.ts';
import { refreshSidebarLists } from '../../app/sidebarLists.ts';
import { getProject, updateProject } from '../../services/projectsService.ts';
import { EditProjectPlaceholder } from './EditProjectPlaceholder.tsx';
import { useProject } from './ProjectContext.tsx';
import { ProjectForm, type ProjectDetails } from './ProjectForm.tsx';

/** Edit a project's details: name, description and assigned users. Its files stay as they are. */
export function EditProjectPage() {
  // The route always names the project.
  const projectId = useParams().projectId!;
  const navigate = useNavigate();
  const resource = useApiResource((signal) => getProject(projectId, signal), [projectId]);
  const action = useAsyncAction((signal, changes: ProjectDetails) => updateProject(projectId, changes, signal));
  // The project's navigation and pages show the saved name and details.
  const { reload } = useProject();
  const project = resource.data?.project?.project_id === projectId ? resource.data.project : null;
  useDocumentTitle(project ? t('Edit {name}', { name: project.name }) : t('Edit project'));
  const back = `/projects/${encodeURIComponent(projectId)}`;
  usePageTitle({
    title: t('Edit project'),
    back: { label: project ? t('Back to {name}', { name: project.name }) : t('Back to the project'), to: back },
  });

  if (resource.error && !project) return <ErrorState error={resource.error} onRetry={resource.reload} />;
  if (!project) return <EditProjectPlaceholder />;
  return (
    <div className="flex flex-col">
      {action.error && <ErrorState error={action.error} title={t('The changes could not be saved')} compact />}
      <ProjectForm
        initial={project}
        submitLabel={t('Save changes')}
        submitIcon={Check}
        pending={action.pending}
        onCancel={() => navigate(back)}
        onSubmit={async (changes) => {
          if (await action.execute(changes)) {
            reload();
            refreshSidebarLists();
            navigate(back);
          }
        }}
      />
    </div>
  );
}
