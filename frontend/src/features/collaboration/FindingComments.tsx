import { Bot, MessageSquare } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button } from '../../components/Button.tsx';
import { t } from '../../i18n/messages.ts';
import { getComments, postComment, putTask, streamAnswer } from '../../services/collaborationService.ts';
import type { CommentThread, Reviewer, TaskInput } from '../../services/apiTypes.ts';
import { formatCount } from '../../utils/format.ts';
import { CommentItem } from './CommentItem.tsx';
import { JoinReviewDialog } from './JoinReviewDialog.tsx';
import { MentionText } from './MentionText.tsx';
import { TaskFields } from './TaskFields.tsx';
import { useCollaboration } from './useCollaboration.ts';
import { usePolling } from './usePolling.ts';
import type { FormEvent } from 'react';

const FIELD =
  'w-full rounded-md border border-hairline bg-surface px-3 py-2 text-body text-ink focus:outline-2 focus:outline-accent';

interface FindingCommentsProps { issueId: string }

export function FindingComments({ issueId }: FindingCommentsProps) {
  const context = useCollaboration();
  const [params] = useSearchParams();
  const [open, setOpen] = useState(Boolean(params.get('comment')));
  const [joining, setJoining] = useState(false);
  const [body, setBody] = useState('');
  const [cursor, setCursor] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestionIndex, setSuggestionIndex] = useState(0);
  // The text before the cursor when Escape closed the suggestions: they stay closed until it changes.
  const [dismissedAt, setDismissedAt] = useState<string | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const section = useRef<HTMLElement>(null);
  const [taskPending, setTaskPending] = useState(false);
  // Desvio's answer as it streams in; kept after it ends until the thread reloads with it.
  const [live, setLive] = useState<{ text: string; done: boolean; data?: CommentThread | null } | null>(null);
  const following = useRef<AbortController | null>(null);
  const resource = usePolling((signal) => getComments(issueId, signal), [issueId], Boolean(context));
  const target = params.get('comment');
  useEffect(() => {
    if (target) setOpen(true);
  }, [target]);
  useEffect(() => {
    if (target && resource.data) {
      const comment = document.getElementById(`comment-${target}`);
      (comment ?? section.current)?.scrollIntoView?.({ block: 'nearest' });
    }
  }, [target, resource.data?.items?.length]);
  const latest = useRef({ data: resource.data, reload: resource.reload });
  latest.current = { data: resource.data, reload: resource.reload };
  function follow() {
    if (following.current) return;
    const controller = new AbortController();
    following.current = controller;
    setLive({ text: '', done: false });
    streamAnswer(issueId, (piece) => setLive((old) => old && { ...old, text: old.text + piece }), controller.signal)
      .catch(() => {}) // polling still brings the stored reply
      .finally(() => {
        if (controller.signal.aborted) return;
        following.current = null;
        setLive((old) => old && { ...old, done: true, data: latest.current.data });
        latest.current.reload();
      });
  }
  // While Desvio writes, the panel stays still: a reader at the bottom follows the reply, one
  // who scrolled up keeps their place (the browser's scroll anchoring holds content above).
  const scrollState = useRef<{ scroller: HTMLElement; height: number; atBottom: boolean } | null>(null);
  useLayoutEffect(() => {
    let scroller = section.current?.parentElement;
    while (scroller && !/(auto|scroll)/.test(getComputedStyle(scroller).overflowY)) scroller = scroller.parentElement;
    if (!scroller) return undefined;
    const before = scrollState.current;
    if (before?.scroller === scroller && before.atBottom && scroller.scrollHeight !== before.height) {
      scroller.scrollTop = scroller.scrollHeight - scroller.clientHeight;
    }
    const measure = () => {
      scrollState.current = {
        scroller,
        height: scroller.scrollHeight,
        atBottom: scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 24,
      };
    };
    measure();
    scroller.addEventListener('scroll', measure, { passive: true });
    return () => scroller.removeEventListener('scroll', measure);
  }, [live?.text, live?.done, resource.data?.items?.length]);
  const botWorking = Boolean(resource.data?.bot_working);
  useEffect(() => {
    if (botWorking) follow();
    // follow() reads the latest thread through refs, so only these two start it again.
  }, [botWorking, issueId]);
  useEffect(
    () => () => {
      following.current?.abort();
      following.current = null;
      setLive(null);
    },
    [issueId],
  );
  if (!context) return null;
  const { reviewer, reviewers, bot } = context;
  const mentionHandles = new Set(['desvio', 'decivio', ...reviewers.map((person) => person.handle.toLowerCase())]);
  // Hidden once the thread has reloaded after the answer ended (it then holds the reply).
  const showLive = live && (!live.done || resource.data === live.data);
  const beforeCursor = body.slice(0, cursor);
  const match = beforeCursor === dismissedAt ? null : beforeCursor.match(/(?:^|\s)@([A-Za-z0-9_]*)$/);
  const mentionable: (Reviewer & { isBot?: boolean })[] = bot ? [{ ...bot, isBot: true }, ...reviewers] : reviewers;
  const suggestions = match
    ? mentionable
        .filter((p) => p.handle !== reviewer?.handle && p.handle.startsWith(match[1].toLowerCase()))
        .slice(0, 6)
    : [];
  function insertMention(person: Reviewer) {
    // Suggestions, the only way here, exist only while the text before the cursor matches.
    const start = cursor - match![1].length - 1;
    const inserted = `@${person.handle} `;
    setBody(body.slice(0, start) + inserted + body.slice(cursor));
    setCursor(start + inserted.length);
    setSuggestionIndex(0);
    input.current?.focus();
    requestAnimationFrame(() => input.current?.setSelectionRange(start + inserted.length, start + inserted.length));
  }
  const task: TaskInput = resource.data?.task ?? {
    assignee: null,
    status: 'todo',
    task_type: null,
    due_date: null,
  };
  async function saveTask(change: Partial<TaskInput>) {
    setTaskPending(true);
    setError(null);
    try {
      await putTask(issueId, {
        assignee: task.assignee,
        status: task.status,
        task_type: task.task_type,
        due_date: task.due_date ?? null,
        ...change,
      });
      resource.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTaskPending(false);
    }
  }
  const comments = resource.data?.items.filter((item) => item.kind !== 'activity') ?? [];
  async function send(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const posted = await postComment(issueId, body);
      if (posted?.bot_replying) follow();
      setBody('');
      setCursor(0);
      resource.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }
  return (
    <section ref={section} aria-label={t('Finding comments')} className="rounded-md border border-hairline bg-surface p-3">
      {!reviewer && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Button variant="primary" onPress={() => setJoining(true)}>
            {t('Choose your name to comment and assign')}
          </Button>
          <JoinReviewDialog open={joining} onOpenChange={setJoining} />
        </div>
      )}
      <TaskFields task={task} reviewers={reviewers} isDisabled={!reviewer || taskPending || !resource.data} onSave={saveTask} />
      <Button icon={MessageSquare} aria-expanded={open} onPress={() => setOpen(!open)}>
        {resource.data ? t('Comments ({count})', { count: formatCount(comments.length) }) : t('Comments')}
      </Button>
      {error && !open && (
        <p role="alert" className="mt-2 text-callout text-danger">
          {error}
        </p>
      )}
      {open && (
        <div className="mt-3 space-y-3">
          {bot && !bot.connected && (
            <p role="note" className="text-caption text-warning">
              {t('Desvio is not connected: this server has no Anthropic API key. It will answer with that message.')}
            </p>
          )}
          {resource.error && (
            <p role="alert" className="text-callout text-danger">
              {resource.error.message}
            </p>
          )}
          {!resource.data && !resource.error && (
            <p role="status" className="text-callout">
              {t('Loading comments…')}
            </p>
          )}
          <ol className="space-y-3">
            {resource.data?.items.map((item) => (
              <CommentItem
                key={item.comment_id}
                item={item}
                isTarget={item.comment_id === target}
                reviewers={reviewers}
                mentionHandles={mentionHandles}
                isTaskDisabled={!reviewer || taskPending}
                onTask={saveTask}
              />
            ))}
          </ol>
          {(showLive || (resource.data?.bot_working && !live)) && (
            <div className="rounded-md border border-hairline bg-surface p-3">
              <p role="status" className="flex items-center gap-1 text-callout font-semibold">
                <Bot aria-hidden="true" className="size-4 text-accent" />
                {bot?.name ?? 'Desvio'}
                <span className="text-caption font-normal text-ink-secondary">
                  {live?.text ? t('Writing…') : t('Thinking…')}
                </span>
              </p>
              {live?.text && (
                <p className="mt-1 whitespace-pre-wrap break-words text-body">
                  <MentionText text={live.text} handles={mentionHandles} />
                </p>
              )}
            </div>
          )}
          {reviewer ? (
            <form onSubmit={send} className="space-y-2">
              <label htmlFor={`comment-body-${issueId}`} className="block text-callout font-medium">
                {t('Comment as {name}', { name: reviewer.name })}
              </label>
              <div className="relative">
              <textarea
                id={`comment-body-${issueId}`}
                ref={input}
                rows={3}
                maxLength={4000}
                required
                className={FIELD}
                placeholder={t('Comment, @mention a teammate or ask @desvio')}
                value={body}
                onChange={(event) => {
                  setBody(event.target.value);
                  setCursor(event.target.selectionStart);
                  setSuggestionIndex(0);
                }}
                onSelect={(event) => setCursor(event.currentTarget.selectionStart)}
                onKeyDown={(event) => {
                  if (!suggestions.length) return;
                  if (event.key === 'Escape') {
                    // Closes only the suggestions, not a dialog or panel around the box.
                    event.preventDefault();
                    event.stopPropagation();
                    setDismissedAt(beforeCursor);
                  }
                  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                    event.preventDefault();
                    setSuggestionIndex(
                      (n) => (n + (event.key === 'ArrowDown' ? 1 : suggestions.length - 1)) % suggestions.length,
                    );
                  }
                  if (event.key === 'Enter' || event.key === 'Tab') {
                    event.preventDefault();
                    insertMention(suggestions[suggestionIndex] ?? suggestions[0]);
                  }
                }}
              />
              {/* Floats above the box, so typing or deleting @ never moves the panel. */}
              {suggestions.length > 0 && (
                <ul
                  aria-label={t('Mention suggestions')}
                  className="absolute inset-x-0 bottom-full z-10 mb-1 rounded-md border border-hairline bg-surface p-1 shadow-lg"
                >
                  {suggestions.map((person, index) => (
                    <li key={person.handle}>
                      <button
                        type="button"
                        className={`w-full rounded px-3 py-2 text-left text-callout hover:bg-state-selected ${index === suggestionIndex ? 'bg-state-selected' : ''}`}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => insertMention(person)}
                      >
                        {person.name} <span className="text-ink-secondary">@{person.handle}</span>
                        {person.isBot && <span className="ml-2 text-caption text-accent">{t('Assistant')}</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              </div>
              {error && (
                <p role="alert" className="text-callout text-danger">
                  {error}
                </p>
              )}
              <Button type="submit" variant="primary" isDisabled={pending || !body.trim()} loading={pending} pendingLabel={t('Sending…')}>
                {t('Send comment')}
              </Button>
            </form>
          ) : null}
        </div>
      )}
    </section>
  );
}
