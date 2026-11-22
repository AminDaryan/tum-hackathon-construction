import { Button } from '../../components/Button.tsx';
import { t } from '../../i18n/messages.ts';
import { recordEmailClarification } from '../../services/clarificationsService.ts';
import type { AssistantAttachments, Reviewer, TaskInput } from '../../services/apiTypes.ts';
import { EmailDraftButton } from '../email/EmailDraft.tsx';
import type { EmailDraft } from '../email/emailDraft.ts';
import { labelOf, TASK_STATUSES } from './tasks.ts';

const STEP = 'h-auto! whitespace-normal! py-2 text-left';

interface AssistantExtrasProps {
  extras: AssistantAttachments;
  reviewers: Reviewer[];
  disabled?: boolean;
  onTask: (change: Partial<TaskInput>) => void;
}

/**
 * What Desvio attached to a reply: an email draft and one-click next steps. In a project the
 * draft is listed among its clarifications (`extras.clarification`); opening it in the email app
 * or copying it marks that clarification sent.
 */
export function AssistantExtras({ extras, reviewers, disabled, onTask }: AssistantExtrasProps) {
  const draft = extras.email_draft;
  const listed = extras.clarification;
  const onSent = listed
    ? (sent: EmailDraft) => {
        recordEmailClarification(listed.project_id, {
          document_id: listed.document_id,
          risk_id: listed.risk_id,
          tier: listed.tier,
          title: listed.title,
          issue_id: listed.issue_id,
          recipient: sent.to,
          subject: sent.subject,
          body: sent.body,
          sent: true,
        }).catch(() => {}); // opening or copying it again retries
      }
    : undefined;
  const nameOf = (handle = '') => reviewers.find((person) => person.handle === handle)?.name ?? handle;
  return (
    <div className="mt-3 space-y-3">
      {draft && (
        <section aria-label={t('Email draft')} className="space-y-2 rounded-md border border-hairline bg-surface-muted p-3">
          <p className="text-caption text-ink-secondary">
            {draft.recipient === 'client' ? t('Email draft to the client') : t('Email draft to the bidder')}
          </p>
          <p className="text-callout font-semibold">{draft.subject}</p>
          <p className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words text-callout">{draft.body}</p>
          <div className="flex flex-wrap items-center gap-2">
            <EmailDraftButton draft={draft} label={t('Open the draft')} variant="primary" onSent={onSent} />
            {listed && <span className="text-caption text-ink-secondary">{t("Listed in the project's Clarifications")}</span>}
          </div>
        </section>
      )}
      {extras.next_steps?.length ? (
        <section aria-label={t('Suggested next steps')}>
          <p className="mb-1 text-caption text-ink-secondary">{t('Suggested next steps')}</p>
          <ul className="flex flex-wrap gap-2">
            {extras.next_steps.map((step) => (
              <li key={step.label}>
                {step.action === 'open_email' && draft ? (
                  <EmailDraftButton draft={draft} label={step.label} className={STEP} onSent={onSent} />
                ) : step.action === 'assign' || step.action === 'set_status' ? (
                  <Button
                    className={STEP}
                    isDisabled={disabled}
                    aria-label={
                      step.action === 'assign'
                        ? t('{step}: assign {name}', { step: step.label, name: nameOf(step.assignee) })
                        : t('{step}: set status to {status}', {
                            step: step.label,
                            status: labelOf(TASK_STATUSES, step.status),
                          })
                    }
                    onPress={() =>
                      onTask(step.action === 'assign' ? { assignee: step.assignee } : { status: step.status })
                    }
                  >
                    {step.label}
                  </Button>
                ) : (
                  <span className="inline-block rounded-md border border-dashed border-hairline px-3 py-2 text-callout">
                    {step.label}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
