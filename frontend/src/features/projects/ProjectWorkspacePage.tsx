import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { projectPath } from '../../app/navigation.ts';
import { usePageTitle } from '../../app/pageTitle.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { t } from '../../i18n/messages.ts';
import { moveProjectFile, removeProjectFile } from '../../services/projectsService.ts';
import { useWorkspace } from '../../stores/useWorkspace.ts';
import { OpenFile } from '../workspace/OpenFile.tsx';
import { AddFilesCard, useAddFiles } from './AddFilesCard.tsx';
import { useOpenFile, useProject } from './ProjectContext.tsx';
import { ProjectFiles } from './ProjectFiles.tsx';
import { groupOf, isCheckingAFile } from './projectOverview.ts';
import { RemoveFileDialog } from './RemoveFileDialog.tsx';

/**
 * The bills and, beside them, Add files over the supporting documents: one column below 1280 px;
 * from there side by side (three fifths and two fifths) and one window tall (less the top bar and
 * the page margins), the bills filling it with as many rows as fit.
 */
const ROW = 'grid gap-4 xl:h-project-page xl:min-h-96 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]';

/**
 * The project's Workspace. With a file in the URL (`?document=`), that file: its sheet, tabs and
 * issue window, titled "Project / file" with the project's name a link to the project. Without
 * one, the project's files to choose from and the box to add more. A file that no longer exists
 * returns here.
 */
export function ProjectWorkspacePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const documentId = params.get('document');
  const { projectId, loaded, project } = useProject();
  const { activeDocumentId, clearActiveDocument } = useWorkspace();
  const start = projectPath(projectId, 'workspace');

  // A file the server no longer has is forgotten by the workspace (activeDocumentId becomes null).
  const seen = useRef<string | null>(null);
  useEffect(() => {
    if (!documentId) return;
    if (activeDocumentId === documentId) seen.current = documentId;
    else if (activeDocumentId === null && seen.current === documentId) navigate(start, { replace: true });
  }, [activeDocumentId, documentId, navigate, start]);

  if (!documentId) return <ChooseFile />;
  return (
    <OpenFile
      documentId={documentId}
      supporting={groupOf(loaded?.groups, { document_id: documentId }) === 'support'}
      parent={{ label: project?.name ?? null, to: projectPath(projectId) }}
      onClose={() => {
        clearActiveDocument();
        navigate(start);
      }}
    />
  );
}

/**
 * The Workspace without an open file: the project's files to open (the project read again when
 * it opens) and the box to add more. While the project loads, the page is already laid out, the
 * files' rows grey.
 */
function ChooseFile() {
  const { projectId, loaded, project, error, reload } = useProject();
  const openFile = useOpenFile();
  const addFiles = useAddFiles(projectId, reload);
  const remove = useAsyncAction((signal, id: string) => removeProjectFile(projectId, id, signal));
  const [removing, setRemoving] = useState<string | null>(null);
  const move = useAsyncAction((signal, id: string, group: 'bill' | 'support') => moveProjectFile(projectId, id, group, signal));
  const documents = useMemo(() => loaded?.documents ?? [], [loaded]);
  // Back from a file, its counts are read again: the decisions made in it change them.
  useEffect(reload, [reload]);
  const checking = isCheckingAFile(documents);
  useEffect(() => {
    if (!checking) return undefined;
    const timer = setInterval(reload, 2000);
    return () => clearInterval(timer);
  }, [checking, reload]);
  useDocumentTitle(t('project.nav.workspace'));
  usePageTitle({
    title: t('project.nav.workspace'),
    back: { label: t('Back to all projects'), to: '/projects' },
  });

  if (error && !project) return <ErrorState error={error} onRetry={reload} />;

  const running = project?.validation?.status === 'running';
  const preparing = project?.preparation === 'preparing';
  const busy = !project || running || preparing || remove.pending || move.pending;
  const removeFile = async (id: string) => {
    setRemoving(null);
    await remove.execute(id);
    reload();
  };
  const moveFile = async (id: string, group: 'bill' | 'support') => {
    await move.execute(id, group);
    reload();
  };
  return (
    <div className="flex flex-col gap-4">
      {(remove.error || move.error) && <ErrorState error={(remove.error ?? move.error)!} title={t('The project could not be updated')} compact />}
      <div className={ROW}>
        <ProjectFiles
          project={project}
          documents={documents}
          reviewCounts={loaded?.review_counts ?? {}}
          onOpen={openFile}
          onRemove={setRemoving}
          onMove={moveFile}
          groups={loaded?.groups}
          disabled={busy}
        />
        <AddFilesCard files={addFiles} disabled={running || preparing} loading={!project} />
      </div>
      <RemoveFileDialog file={documents.find((doc) => doc.document_id === removing) ?? null} onCancel={() => setRemoving(null)} onConfirm={removeFile} />
    </div>
  );
}
