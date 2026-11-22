import { Bot } from 'lucide-react';
import { intlLocale, t } from '../../i18n/messages.ts';
import type { CommentThread, Reviewer, TaskInput } from '../../services/apiTypes.ts';
import { AssistantExtras } from './AssistantExtras.tsx';
import { MentionText } from './MentionText.tsx';

interface CommentItemProps {
  item: CommentThread['items'][number];
  isTarget: boolean;
  reviewers: Reviewer[];
  mentionHandles: ReadonlySet<string>;
  isTaskDisabled: boolean;
  onTask: (change: Partial<TaskInput>) => void;
}

const time = (iso: string) => new Date(iso).toLocaleTimeString(intlLocale(), { hour: '2-digit', minute: '2-digit' });

/** One entry of a finding's thread: a task change as a line, or a comment with its author. */
export function CommentItem({ item, isTarget, reviewers, mentionHandles, isTaskDisabled, onTask }: CommentItemProps) {
  if (item.kind === 'activity') {
    return (
      <li
        id={`comment-${item.comment_id}`}
        className={`px-3 text-caption text-ink-secondary ${isTarget ? 'rounded-md bg-state-selected py-2 ring-1 ring-accent' : ''}`}
      >
        <span className="font-semibold text-ink">{item.author_name}</span> <span>{item.body}</span>{' '}
        <time dateTime={item.created_at} className="text-ink-tertiary">
          {time(item.created_at)}
        </time>
      </li>
    );
  }
  return (
    <li
      id={`comment-${item.comment_id}`}
      className={`rounded-md p-3 ${isTarget ? 'bg-state-selected ring-1 ring-accent' : ['desvio', 'decivio'].includes(item.author) ? 'border border-hairline bg-surface' : 'bg-surface-muted'}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="flex items-center gap-1 text-callout font-semibold">
          {['desvio', 'decivio'].includes(item.author) && <Bot aria-hidden="true" className="size-4 text-accent" />}
          {item.author_name}
          {['desvio', 'decivio'].includes(item.author) && <span className="text-caption font-normal text-ink-secondary">{t('Assistant')}</span>}
        </span>
        <time dateTime={item.created_at} className="text-caption text-ink-tertiary">
          {time(item.created_at)}
        </time>
      </div>
      <p className="mt-1 whitespace-pre-wrap break-words text-body">
        <MentionText text={item.body} handles={mentionHandles} />
      </p>
      {item.assistant && (
        <AssistantExtras extras={item.assistant} reviewers={reviewers} disabled={isTaskDisabled} onTask={onTask} />
      )}
    </li>
  );
}
