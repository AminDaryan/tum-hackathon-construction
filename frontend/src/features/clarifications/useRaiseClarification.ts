import { useCallback } from 'react';
import { useMatch } from 'react-router-dom';
import { createClarification, recordEmailClarification } from '../../services/clarificationsService.ts';
import { useWorkspace } from '../../stores/useWorkspace.ts';
import type { Risk } from '../../services/apiTypes.ts';
import type { EmailDraft } from '../email/emailDraft.ts';

/**
 * Lists a risk among the clarifications of the project whose Workspace is open
 * (`/projects/:projectId/workspace`), as a question to the client until a reviewer says who is asked. A bill opened
 * outside a project has no such list: the returned function then resolves with null.
 */
export function useRaiseClarification(): (risk: Risk, title?: string) => Promise<object | null> {
  const projectId = useMatch('/projects/:projectId/*')?.params.projectId ?? null;
  const { activeDocumentId } = useWorkspace();
  return useCallback(
    async (risk, title) => {
      if (!projectId || !activeDocumentId) return null;
      return createClarification(projectId, {
        document_id: activeDocumentId,
        risk_id: risk.risk_id,
        tier: risk.tier,
        title: (title || risk.title).slice(0, 300),
      });
    },
    [projectId, activeDocumentId],
  );
}

/**
 * Marks an email about a risk as sent among the clarifications of the project whose Workspace is
 * open: the risk's bidder question takes the email and becomes sent (a new one when it has none).
 * Null outside a project. A failure leaves the email app or clipboard to do its job: nothing is
 * shown, and opening or copying the email again retries.
 */
export function useMarkEmailSent():
  | ((risk: Pick<Risk, 'risk_id' | 'tier' | 'title'>, title: string, issueId: string | null, draft: EmailDraft) => void)
  | null {
  const projectId = useMatch('/projects/:projectId/*')?.params.projectId ?? null;
  const { activeDocumentId } = useWorkspace();
  const mark = useCallback(
    (risk: Pick<Risk, 'risk_id' | 'tier' | 'title'>, title: string, issueId: string | null, draft: EmailDraft) => {
      // Only returned (below) with a project and a file.
      recordEmailClarification(projectId!, {
        document_id: activeDocumentId!,
        risk_id: risk.risk_id,
        tier: risk.tier,
        title: (title || risk.title).slice(0, 300),
        issue_id: issueId,
        recipient: draft.to,
        subject: draft.subject,
        body: draft.body,
        sent: true,
      }).catch(() => {});
    },
    [projectId, activeDocumentId],
  );
  return projectId && activeDocumentId ? mark : null;
}
