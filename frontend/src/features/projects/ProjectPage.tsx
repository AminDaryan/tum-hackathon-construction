import { Pencil, ShieldCheck } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { usePageTitle } from '../../app/pageTitle.tsx';
import { Banner } from '../../components/Banner.tsx';
import { Button, ButtonLink } from '../../components/Button.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { Select } from '../../components/Select.tsx';
import { Skeleton } from '../../components/Skeleton.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { t } from '../../i18n/messages.ts';
import { moveProjectFile, removeProjectFile, updateProject, validateProject } from '../../services/projectsService.ts';
import type { Project } from '../../services/apiTypes.ts';
import { pluralize } from '../../utils/format.ts';
import { AddFilesCard, useAddFiles } from './AddFilesCard.tsx';
import { FollowUpsCard } from './FollowUpsCard.tsx';
import { ProjectOverview } from './overview/ProjectOverview.tsx';
import { useOpenFile, useProject } from './ProjectContext.tsx';
import { ProjectFiles } from './ProjectFiles.tsx';
import { isCheckingAFile, readableBills } from './projectOverview.ts';
import { RemoveFileDialog } from './RemoveFileDialog.tsx';
import { PROJECT_STATUS } from './projectStatus.ts';

/**
 * The four boxes: one column below 1280 px; from there two rows filling the window (three fifths
 * and two fifths of its height) of two columns (three fifths and two fifths of its width).
 */
const GRID = 'grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] xl:grid-rows-[3fr_2fr]';

const STATUS_OPTIONS = Object.entries(PROJECT_STATUS).map(([value, { label }]) => ({ value, label }));

/**
 * One project's Overview, in one window from 1280 px wide and about 1130 px high (the tables
 * show as many rows as fit; a lower window scrolls), titled like its menu item, with the way
 * back to all projects. First row: the project overview, with Edit and the project's status (a
 * dropdown to change it) at its top right, its figures and its risks; beside it the follow-ups.
 * Second row: the bills, with Validate project at their top right; beside them the box to add
 * files and the supporting documents (drawings, reports, specs), which open as the documents
 * themselves.
 *
 * The project is loaded once for all its pages (ProjectProvider) and read again when this page
 * opens; while it loads the page is already laid out, its figures and rows grey. Opening a file
 * goes to the project's Workspace.
 */
export function ProjectPage() {
  const location = useLocation();
  const { projectId, loaded, project, error, reload, overviewFileFilters, setOverviewFileFilters } = useProject();
  const openFile = useOpenFile();
  const action = useAsyncAction(async (signal, run: (signal: AbortSignal) => Promise<unknown>) => run(signal));
  const addFiles = useAddFiles(projectId, reload);
  const [removing, setRemoving] = useState<string | null>(null);
  useDocumentTitle(t('project.nav.overview'));
  usePageTitle({
    title: t('project.nav.overview'),
    back: { label: t('Back to all projects'), to: '/projects' },
  });

  const documents = useMemo(() => loaded?.documents ?? [], [loaded]);
  const reviewCounts = useMemo(() => loaded?.review_counts ?? {}, [loaded]);
  const groups = loaded?.groups;
  const bills = useMemo(() => (project ? readableBills(project, documents) : []), [project, documents]);
  const preparing = project?.preparation === 'preparing';
  const running = project?.validation?.status === 'running';
  const checking = isCheckingAFile(documents);

  // The project is loaded once for all its pages: decisions made in the Workspace since change
  // its counts and risks, so they are read again (the last ones stay on screen meanwhile).
  useEffect(reload, [reload]);

  useEffect(() => {
    if (!preparing && !running && !checking) return undefined;
    const timer = setInterval(reload, 2000);
    return () => clearInterval(timer);
  }, [preparing, running, checking, reload]);

  const change = useCallback(
    async (run: (signal: AbortSignal) => Promise<unknown>) => {
      await action.execute(run);
      reload();
    },
    [action, reload],
  );

  if (error && !project) return <ErrorState error={error} onRetry={reload} />;

  const validate = () => change((signal) => validateProject(projectId, signal));
  const moveFile = (documentId: string, group: 'bill' | 'support') => change((signal) => moveProjectFile(projectId, documentId, group, signal));
  const setStatus = (status: Project['status']) => change((signal) => updateProject(projectId, { status }, signal));
  const warnings: string[] = (location.state as { uploadWarnings?: string[] } | null)?.uploadWarnings ?? [];
  const busy = !project || running || preparing || action.pending;

  const validateButton = bills.length > 0 && (
    <Button
      variant="primary"
      icon={ShieldCheck}
      loading={running || action.pending}
      pendingLabel={t('Validating…')}
      isDisabled={preparing}
      onPress={running ? undefined : validate}
    >
      {t('Validate project')}
    </Button>
  );
  const validationFailed = project?.validation?.status === 'failed' && (
    <p role="alert" className="text-callout text-danger">
      {project.validation.error
        ? t('The last validation of this project failed: {error}', { error: project.validation.error })
        : t('The last validation of this project failed.')}
    </p>
  );

  return (
    // One window tall, but never shorter than room for five risks and four bills: a lower window
    // (a 1280 × 720 projector) scrolls instead of squeezing the lists to a row.
    <div className="flex flex-col gap-4 xl:h-[max(var(--spacing-project-page),65rem)]">
      {warnings.length > 0 && (
        <Banner tone="danger" title={
            warnings.length === 1
              ? t('{file} could not be added', { file: pluralize(1, 'file') })
              : t('{files} could not be added', { files: pluralize(warnings.length, 'file') })
          }>
          <ul className="break-words">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Banner>
      )}
      {project?.preparation === 'failed' && (
        <Banner tone="danger" title={t('The demo files could not be prepared.')}>
          {project.preparation_error}
        </Banner>
      )}
      {action.error && <ErrorState error={action.error} title={t('The project could not be updated')} compact />}
      <div className={GRID}>
        <ProjectOverview
          projectId={projectId}
          project={project}
          documents={documents}
          reviewCounts={reviewCounts}
          groups={groups}
          onOpenIssue={openFile}
          className="max-xl:h-[40rem]"
          actions={
            <>
              <ButtonLink to={`/projects/${encodeURIComponent(projectId)}/edit`} variant="ghost" icon={Pencil}>
                {t('Edit')}
              </ButtonLink>
              {project ? (
                <Select
                  label={t('Status')}
                  hideLabel
                  value={project.status}
                  options={STATUS_OPTIONS.map((option) => ({ ...option, label: t(option.label) }))}
                  onChange={(status) => setStatus(status === 'finished' ? 'finished' : 'in_progress')}
                  disabled={action.pending}
                />
              ) : (
                <Skeleton className="h-8 w-28" />
              )}
            </>
          }
        />
        <FollowUpsCard projectId={projectId} documents={project ? documents : null} onOpen={openFile} className="max-xl:h-[28rem]" />
        <ProjectFiles
          filters={overviewFileFilters}
          onFiltersChange={setOverviewFileFilters}
          project={project}
          documents={documents}
          reviewCounts={reviewCounts}
          onOpen={openFile}
          onRemove={setRemoving}
          onMove={moveFile}
          groups={groups}
          disabled={busy}
          action={validateButton}
          footer={validationFailed}
        />
        <AddFilesCard files={addFiles} disabled={running || preparing} loading={!project} />
      </div>
      <RemoveFileDialog
        file={documents.find((doc) => doc.document_id === removing) ?? null}
        onCancel={() => setRemoving(null)}
        onConfirm={(documentId) => {
          setRemoving(null);
          void change((signal) => removeProjectFile(projectId, documentId, signal));
        }}
      />
    </div>
  );
}
