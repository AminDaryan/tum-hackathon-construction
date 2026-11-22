import { usePageTitle } from '../../app/pageTitle.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { t } from '../../i18n/messages.ts';
import { ClarificationsPanel } from '../clarifications/ClarificationsPanel.tsx';
import { openClarificationRisk } from './FollowUpsCard.tsx';
import { useOpenFile, useProject } from './ProjectContext.tsx';

/**
 * Follow-ups of a project: the list of its clarifications, the questions to settle before the bid
 * decision, each raised on a risk or an email drafted about it. A clarification's "Open the risk"
 * opens that risk in the Workspace, on the finding its email was about when it has one. While the
 * project loads, the page is already laid out, its list grey.
 */
export function FollowUpsPage() {
  const { projectId, loaded, project, error, reload } = useProject();
  const openFile = useOpenFile();
  useDocumentTitle(t('project.nav.followUps'));
  usePageTitle({
    title: t('project.nav.followUps'),
    back: { label: t('Back to all projects'), to: '/projects' },
  });

  if (error && !project) return <ErrorState error={error} onRetry={reload} />;
  const busy = project?.validation?.status === 'running' || project?.preparation === 'preparing';

  return (
    <ClarificationsPanel
      projectId={projectId}
      cutoff={project?.decision_cutoff}
      documents={project ? (loaded?.documents ?? []) : null}
      disabled={busy}
      onOpenRisk={(item) => openClarificationRisk(openFile, item)}
      onCutoffSaved={reload}
    />
  );
}
