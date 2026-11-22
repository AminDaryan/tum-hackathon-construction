import { Timestamp } from '../../components/Timestamp.tsx';
import { t, tRich } from '../../i18n/messages.ts';
import { AUDIT_ACTION_LABELS, labelFor, statusMeta } from '../../utils/vocabulary.ts';
import type { AuditEvent } from '../../services/apiTypes.ts';

interface StatusChangeProps {
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
}

function StatusChange({ before, after }: StatusChangeProps) {
  const from = before?.review_status as string | undefined;
  const to = after?.review_status as string | undefined;
  if (!from && !to) {
    return null;
  }
  return (
    <p className="text-callout text-ink">
      {from ? t(statusMeta('review', from).label) : '—'} → {to ? t(statusMeta('review', to).label) : '—'}
    </p>
  );
}

interface AuditHistoryProps {
  events?: AuditEvent[];
}

/** The audit trail of an issue, oldest first. Every review decision appends one event. */
export function AuditHistory({ events }: AuditHistoryProps) {
  if (!events?.length) return null;
  const ordered = [...events].sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at));
  return (
    <ol className="space-y-3">
      {ordered.map((event) => {
        const comment = event.after?.reviewer_comment;
        return (
          <li key={event.event_id} className="border-l-2 border-hairline pl-3">
            <p className="text-callout font-medium text-ink">{t(labelFor(AUDIT_ACTION_LABELS, event.action))}</p>
            <StatusChange before={event.before} after={event.after} />
            <p className="text-callout text-ink-secondary">{event.summary}</p>
            {typeof comment === 'string' && comment && (
              <p className="mt-1 whitespace-pre-line text-callout text-ink">“{comment}”</p>
            )}
            <p className="mt-0.5 text-caption text-ink-tertiary">
              {event.actor ? (
                tRich('{time} by {actor}', { time: <Timestamp value={event.occurred_at} />, actor: event.actor })
              ) : (
                <Timestamp value={event.occurred_at} />
              )}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
