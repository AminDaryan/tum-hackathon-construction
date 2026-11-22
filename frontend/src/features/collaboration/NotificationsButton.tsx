import { Bell } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Button as AriaButton } from 'react-aria-components';
import { useNavigate } from 'react-router-dom';
import { HIT_SQUARE } from '../../components/hitTarget.ts';
import { t } from '../../i18n/messages.ts';
import { readNotification } from '../../services/collaborationService.ts';
import type { MentionNotification } from '../../services/apiTypes.ts';
import { useWorkspace } from '../../stores/useWorkspace.ts';
import { cx } from '../../utils/classNames.ts';
import { formatCount } from '../../utils/format.ts';
import { useCollaboration } from './useCollaboration.ts';

/**
 * The reviewer's mentions and assignments, as a bell in the top bar with the unread count; shown
 * once this browser has a reviewer name. Opening one goes to its finding and marks it read.
 * Escape or a click outside closes the list.
 */
export function NotificationsButton() {
  const context = useCollaboration();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const { setActiveDocumentId } = useWorkspace();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const dismiss = (event: KeyboardEvent | PointerEvent) => {
      if (event.type === 'keydown' && (event as KeyboardEvent).key === 'Escape') {
        setOpen(false);
        button.current?.focus();
      } else if (event.type === 'pointerdown' && !root.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('keydown', dismiss);
    document.addEventListener('pointerdown', dismiss);
    return () => {
      document.removeEventListener('keydown', dismiss);
      document.removeEventListener('pointerdown', dismiss);
    };
  }, [open]);
  if (!context?.reviewer) return null;
  const { reviewer, inbox } = context;
  const unread = inbox.data?.unread_count ?? 0;
  async function openNotification(item: MentionNotification) {
    setError(null);
    try {
      // Only mark read after the navigation has been requested successfully.
      setActiveDocumentId(item.document_id);
      const query = new URLSearchParams({
        document: item.document_id,
        run: item.validation_run_id,
        issue: item.issue_id,
        tab: 'risks',
        comment: item.comment_id,
      });
      navigate(`/workspace?${query}`);
      setOpen(false);
      await readNotification(item.notification_id);
      inbox.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <div ref={root} className="relative">
      <button
        ref={button}
        type="button"
        aria-label={t('Notifications, {count} unread', { count: formatCount(unread) })}
        title={t('Notifications')}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={cx(
          'state-layer relative inline-flex cursor-pointer items-center justify-center rounded-full text-ink-secondary transition-colors hover:text-ink',
          HIT_SQUARE,
          open && 'bg-state-selected text-ink',
        )}
      >
        <Bell aria-hidden="true" className="size-4" strokeWidth={1.75} />
        {unread > 0 && (
          <span
            aria-hidden="true"
            className="absolute right-1.5 top-1.5 inline-flex min-w-4 justify-center rounded-full bg-accent px-1 text-[0.625rem] font-semibold leading-4 text-on-accent"
          >
            {unread > 99 ? '99+' : formatCount(unread)}
          </span>
        )}
      </button>
      {open && (
        <section
          aria-label={t('Notifications')}
          className="absolute right-0 top-full z-40 mt-2 max-h-[65vh] w-96 max-w-[calc(100vw-2rem)] overflow-y-auto rounded-lg border border-hairline bg-surface p-4 shadow-overlay"
        >
          <h2 className="mb-3 text-headline">{t('Notifications')}</h2>
          {inbox.error && (
            <p role="status" className="mb-3 text-callout text-ink-secondary">
              {t('The notifications could not be loaded. Trying again…')}
            </p>
          )}
          {error && (
            <p role="alert" className="mb-3 text-callout text-danger">
              {error}
            </p>
          )}
          {inbox.data && !inbox.data.items?.length && (
            <p className="text-callout text-ink-secondary">
              {t('No mentions yet. Teammates can mention {handle} in a finding comment.', { handle: `@${reviewer.handle}` })}
            </p>
          )}
          <ul className="space-y-2">
            {inbox.data?.items?.map((item) => (
              <li key={item.notification_id}>
                <AriaButton
                  className={`w-full cursor-pointer rounded-md border border-hairline p-3 text-left hover:bg-state-selected ${item.is_read ? '' : 'bg-state-selected'}`}
                  onPress={() => openNotification(item)}
                >
                  <span className="block text-callout font-semibold">
                    {item.kind === 'activity'
                      ? t('{name} assigned you', { name: item.author_name })
                      : ['desvio', 'decivio'].includes(item.author)
                        ? t('{name} replied to you', { name: item.author_name })
                        : t('{name} mentioned you', { name: item.author_name })}
                    {!item.is_read && <span className="ml-2 text-accent">{t('New')}</span>}
                  </span>
                  <span className="mt-1 block text-caption text-ink-secondary">{item.issue_title}</span>
                  <span className="mt-2 block whitespace-pre-wrap break-words text-body">{item.body}</span>
                </AriaButton>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
