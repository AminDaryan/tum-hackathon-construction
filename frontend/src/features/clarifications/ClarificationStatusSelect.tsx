import { CircleCheck, MessageSquareReply, PencilLine, Send } from 'lucide-react';
import { StatusSelect, type StatusOption } from '../../components/StatusSelect.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { t } from '../../i18n/messages.ts';
import { saveClarification, type Clarification, type ClarificationItem } from '../../services/clarificationsService.ts';
import { useSession } from '../../stores/useSession.ts';
import { kindOf, STATUSES, statusText } from './clarificationModel.ts';
import type { BadgeTone } from '../../components/Badge.tsx';
import type { LucideIcon } from 'lucide-react';

const STATUS_LOOK: Readonly<Record<Clarification['status'], { icon: LucideIcon; tone: BadgeTone }>> = Object.freeze({
  draft: { icon: PencilLine, tone: 'neutral' },
  sent: { icon: Send, tone: 'context' },
  answered: { icon: MessageSquareReply, tone: 'accent' },
  decided: { icon: CircleCheck, tone: 'success' },
});

interface ClarificationStatusSelectProps {
  item: ClarificationItem;
  /** the status was saved: the list is read again */
  onSaved: () => void;
}

/**
 * How far a clarification is, in its row of the list, changed there: Draft, Sent (in the words of
 * whoever is asked: "Waiting for reply", "On agenda"), Answered or Decided, saved at once with the
 * rest of the clarification as it is. A question the app only suggested (not saved yet) stays
 * "Suggested", and a viewer sees the badge alone.
 */
export function ClarificationStatusSelect({ item, onSaved }: ClarificationStatusSelectProps) {
  const { can } = useSession();
  const { clarification_id: id } = item;
  const save = useAsyncAction((signal, savedId: string, status: Clarification['status']) =>
    saveClarification(savedId, { kind: item.kind, title: item.title, status, due: item.due, phase: item.phase, answer: item.answer }, signal),
  );
  if (id === null) return <span className="text-ink-secondary">{statusText(item)}</span>;
  const options: StatusOption<Clarification['status']>[] = STATUSES.map((status) => ({
    value: status.value,
    label: status.value === 'sent' ? t(kindOf(item.kind).sent) : t(status.label),
    ...STATUS_LOOK[status.value],
  }));
  return (
    <div className="flex flex-col items-start">
      <StatusSelect
        label={t('Status of {name}', { name: item.title })}
        value={item.status}
        options={options}
        onChange={async (status) => {
          if (await save.execute(id, status)) onSaved();
        }}
        readOnly={!can('write')}
        disabled={save.pending}
      />
      {save.error && (
        <p role="alert" className="text-caption text-danger">
          {t('The changes could not be saved')}
        </p>
      )}
    </div>
  );
}
