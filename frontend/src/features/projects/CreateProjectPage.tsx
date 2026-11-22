import { FileText, Plus, X } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ErrorState } from '../../components/ErrorState.tsx';
import { IconButton } from '../../components/IconButton.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { usePageTitle } from '../../app/pageTitle.tsx';
import { t } from '../../i18n/messages.ts';
import { refreshSidebarLists } from '../../app/sidebarLists.ts';
import { createProject } from '../../services/projectsService.ts';
import { formatBytes } from '../../utils/format.ts';
import { isAcceptedFile, rejectionMessage } from '../documents/uploadRules.ts';
import { FilesDropzone } from './FilesDropzone.tsx';
import { ProjectForm, type ProjectDetails } from './ProjectForm.tsx';
import { uploadToProject } from './projectUpload.ts';

const fileKey = (file: File) => `${file.name}/${file.size}/${file.lastModified}`;

/**
 * Create project: the details (name, description, assigned users) and the project's files,
 * one or several. Creating stores the project, then adds each file as a bill, one at a time; a
 * file that fails does not stop the others. The project's page opens afterwards and names the
 * files that were not added.
 */
export function CreateProjectPage() {
  useDocumentTitle(t('Create project'));
  usePageTitle({
    title: t('Create project'),
    back: { label: t('Back to all projects'), to: '/projects' },
  });
  const navigate = useNavigate();
  const [files, setFiles] = useState<File[]>([]);
  const [rejected, setRejected] = useState<string[]>([]);
  const [progress, setProgress] = useState('');
  const action = useAsyncAction(async (signal, details: ProjectDetails, chosen: File[]) => {
    const project = await createProject(details, signal);
    const failures = chosen.length ? await uploadToProject(project.project_id, chosen, { signal, onProgress: setProgress }) : [];
    return { project, failures };
  });

  const choose = (list: File[]) => {
    const accepted = list.filter(isAcceptedFile);
    setRejected(list.filter((file) => !isAcceptedFile(file)).map(rejectionMessage));
    setFiles((current) => {
      const seen = new Set(current.map(fileKey));
      return [...current, ...accepted.filter((file) => !seen.has(fileKey(file)))];
    });
  };

  return (
    <div className="flex flex-col">
      {action.error && <ErrorState error={action.error} title={t('The project could not be created')} compact />}
      <ProjectForm
        initial={{}}
        assignSelf
        submitLabel={t('Create project')}
        submitIcon={Plus}
        pending={action.pending}
        onCancel={() => navigate('/projects')}
        onSubmit={async (details) => {
          const result = await action.execute(details, files);
          if (result) {
            refreshSidebarLists();
            navigate(`/projects/${encodeURIComponent(result.project.project_id)}`, {
              state: { uploadWarnings: result.failures },
            });
          }
        }}
      >
        <section aria-labelledby="create-project-files" className="flex flex-col gap-4 rounded-lg border border-hairline bg-surface p-5">
          <div>
            <h2 id="create-project-files" className="text-headline text-ink">
              {t('Files')}
            </h2>
            <p className="text-caption text-ink-secondary">{t('Optional now: you can add more files on the project’s page later.')}</p>
          </div>
          <FilesDropzone onFiles={choose} disabled={action.pending} />
          {rejected.length > 0 && (
            <ul role="alert" className="flex flex-col gap-1 text-callout text-danger">
              {rejected.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          )}
          {files.length > 0 && (
            <ul aria-label={t('Chosen files')} className="divide-y divide-hairline rounded-md border border-hairline">
              {files.map((file) => (
                <li key={fileKey(file)} className="flex items-center gap-3 py-1 pl-3 pr-1">
                  <FileText aria-hidden="true" className="size-4 shrink-0 text-ink-tertiary" />
                  <span className="min-w-0 flex-1 break-all text-callout text-ink">{file.name}</span>
                  <span className="shrink-0 text-caption text-ink-secondary">{formatBytes(file.size)}</span>
                  <IconButton
                    icon={X}
                    label={t('Remove {name}', { name: file.name })}
                    isDisabled={action.pending}
                    onPress={() => setFiles((current) => current.filter((other) => fileKey(other) !== fileKey(file)))}
                  />
                </li>
              ))}
            </ul>
          )}
          {action.pending && progress && (
            <p role="status" className="text-callout text-ink-secondary">
              {progress}
            </p>
          )}
        </section>
      </ProjectForm>
    </div>
  );
}
