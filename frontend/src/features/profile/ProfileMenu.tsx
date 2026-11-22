import { Check, LogOut, Settings, UserPlus, UserRound } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { HIT_MIN_HEIGHT, HIT_TARGET } from '../../components/hitTarget.ts';
import { Skeleton } from '../../components/Skeleton.tsx';
import { useI18n } from '../../i18n/useI18n.ts';
import { useSession } from '../../stores/useSession.ts';
import { cx } from '../../utils/classNames.ts';
import { fadeOut } from '../../utils/motion.ts';
import { JoinReviewDialog } from '../collaboration/JoinReviewDialog.tsx';
import { useChooseReviewer } from '../collaboration/useChooseReviewer.ts';
import { useCollaboration } from '../collaboration/useCollaboration.ts';
import { useOpenProfile, useOpenSettings } from '../settings/SettingsDialog.tsx';
import { Avatar } from './Avatar.tsx';
import { displayName } from './ProfileParts.tsx';

const ITEM = cx(
  'state-layer flex w-full cursor-pointer items-center gap-2.5 rounded-md px-3 text-left text-callout font-medium outline-none transition-colors focus-visible:bg-state-selected',
  HIT_MIN_HEIGHT,
);
const GROUP_LABEL = 'px-3 pb-1 pt-2 text-caption font-medium text-ink-tertiary';
const SEPARATOR = 'my-1.5 border-t border-hairline';
/** Reviewer names offered for a one-click switch; more are in the Choose reviewer dialog. */
const SHOWN_REVIEWERS = 5;

/**
 * The avatar at the top right, the initials of the person signed in, and on click the user menu:
 * their name and role, then Profile and Settings, which open over the page; the reviewer name
 * this browser comments as (one click switches, or join with a new name); and Log out.
 * Arrow keys, Home and End move between the items; Escape, a click outside or moving the focus out closes it, and Escape
 * returns the focus to the avatar. Log out is unavailable when this tab is not signed in.
 */
export function ProfileMenu() {
  const { t } = useI18n();
  const { me, meError, signedIn, signOut } = useSession();
  const openProfile = useOpenProfile();
  const openSettings = useOpenSettings();
  const collaboration = useCollaboration();
  const { choose, pending: switching, error: reviewerError, clearError } = useChooseReviewer();
  const [open, setOpen] = useState(false);
  const [joining, setJoining] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close();
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  useLayoutEffect(() => {
    if (open) menuRef.current?.querySelector<HTMLElement>('[role^="menuitem"]')?.focus();
  }, [open]);

  // The menu fades out before it goes.
  const close = ({ refocus = false } = {}) => {
    if (refocus) buttonRef.current?.focus();
    fadeOut(menuRef.current, () => setOpen(false));
  };

  const moveFocus = (event: KeyboardEvent<HTMLElement>) => {
    const items = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])];
    const index = items.indexOf(document.activeElement as HTMLElement);
    const targets: Record<string, number> = {
      ArrowDown: (index + 1) % items.length,
      ArrowRight: (index + 1) % items.length,
      ArrowUp: (index - 1 + items.length) % items.length,
      ArrowLeft: (index - 1 + items.length) % items.length,
      Home: 0,
      End: items.length - 1,
    };
    const next = targets[event.key];
    if (next === undefined || items.length === 0) return;
    event.preventDefault();
    items[next].focus();
  };

  // The reviewer names, once the collaboration service answered: this browser's first.
  const reviewer = collaboration?.reviewer ?? null;
  const reviewers = collaboration?.session.data
    ? [...(reviewer ? [reviewer] : []), ...collaboration.reviewers.filter((person) => person.handle !== reviewer?.handle)].slice(
        0,
        SHOWN_REVIEWERS,
      )
    : null;

  const name = displayName(me, t);
  const accountLabel = me ? t('profile.open', { name }) : t('profile.menu');
  const label = reviewer ? `${accountLabel}, ${t('profile.currentReviewer', { name: reviewer.name })}` : accountLabel;
  return (
    <>
      <div
        ref={rootRef}
        className="relative"
        onKeyDown={(event) => {
          if (event.key === 'Escape' && open) {
            event.stopPropagation();
            close({ refocus: true });
          }
        }}
        onBlur={(event) => {
          if (open && event.relatedTarget && !rootRef.current?.contains(event.relatedTarget as Node)) close();
        }}
      >
        <button
          ref={buttonRef}
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          aria-label={label}
          title={label}
          onClick={() => {
            if (open) {
              close();
            } else {
              clearError();
              setOpen(true);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown' && !open) {
              event.preventDefault();
              clearError();
              setOpen(true);
            }
          }}
          className={cx(
            'state-layer inline-flex cursor-pointer items-center justify-center gap-2 rounded-full p-1 transition-colors',
            HIT_TARGET,
            open && 'bg-state-selected',
          )}
        >
          {reviewer && (
            <span aria-hidden="true" className="min-w-0 max-w-32 pl-2 text-right max-sm:max-w-20">
              <span className="block text-caption leading-tight text-ink-tertiary">{t('role.reviewer')}</span>
              <span className="block truncate text-callout leading-tight text-ink">{reviewer.name}</span>
            </span>
          )}
          {me ? (
            <Avatar name={name} role={me.role} />
          ) : meError ? (
            // GET /me failed: who is signed in is unknown, so a plain person instead of a grey shape that never ends.
            <span aria-hidden="true" className="inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-muted text-ink-secondary">
              <UserRound className="size-4" strokeWidth={1.75} />
            </span>
          ) : (
            // Until GET /me answers: the avatar as a grey circle of its size.
            <Skeleton className="size-8 shrink-0 rounded-full" />
          )}
        </button>
        {open && (
          <div
            ref={menuRef}
            id={menuId}
            role="menu"
            aria-label={t('profile.menu')}
            onKeyDown={moveFocus}
            className="absolute right-0 top-full z-40 mt-2 w-64 origin-top-right rounded-lg border border-hairline bg-surface p-1.5 shadow-overlay motion-safe:animate-[drop-in_160ms_var(--ease-standard)]"
          >
            {me && (
              // Said already by the avatar's name; here for the eye, so it is hidden from screen readers.
              <>
                <div aria-hidden="true" className="flex min-w-0 flex-col px-3 pb-2 pt-1.5">
                  <span className="truncate text-callout font-medium text-ink">{name}</span>
                  <span className="truncate text-caption text-ink-secondary">{t(`role.${me.role}`)}</span>
                </div>
                <div role="separator" className={SEPARATOR} />
              </>
            )}
            <button
              type="button"
              role="menuitem"
              tabIndex={-1}
              className={cx(ITEM, 'text-ink')}
              onClick={() => {
                close();
                openProfile();
              }}
            >
              <UserRound aria-hidden="true" className="size-4 text-ink-secondary" strokeWidth={1.75} />
              {t('menu.profile')}
            </button>
            <button
              type="button"
              role="menuitem"
              aria-haspopup="dialog"
              tabIndex={-1}
              className={cx(ITEM, 'text-ink')}
              onClick={() => {
                close();
                openSettings();
              }}
            >
              <Settings aria-hidden="true" className="size-4 text-ink-secondary" strokeWidth={1.75} />
              {t('nav.settings')}
            </button>

            {reviewers && (
              <>
                <div role="separator" className={SEPARATOR} />
                <div role="group" aria-label={t('role.reviewer')}>
                  <p aria-hidden="true" className={GROUP_LABEL}>
                    {t('role.reviewer')}
                  </p>
                  {reviewers.map((person) => {
                    const current = person.handle === reviewer?.handle;
                    return (
                      <button
                        key={person.handle}
                        type="button"
                        role="menuitemradio"
                        aria-checked={current}
                        aria-disabled={switching || undefined}
                        tabIndex={-1}
                        className={cx(ITEM, 'text-ink')}
                        onClick={async () => {
                          if (switching) return;
                          if (current || (await choose(person.name))) close({ refocus: true });
                        }}
                      >
                        <span className="min-w-0 flex-1 truncate">{person.name}</span>
                        {current && <Check aria-hidden="true" className="size-4 shrink-0 text-accent" strokeWidth={2} />}
                      </button>
                    );
                  })}
                  <button
                    type="button"
                    role="menuitem"
                    tabIndex={-1}
                    className={cx(ITEM, 'text-ink')}
                    onClick={() => {
                      close();
                      setJoining(true);
                    }}
                  >
                    <UserPlus aria-hidden="true" className="size-4 text-ink-secondary" strokeWidth={1.75} />
                    {t(reviewer ? 'Join as someone else…' : 'Choose reviewer…')}
                  </button>
                  {reviewerError && (
                    <p role="alert" className="px-3 pb-1 text-caption text-danger">
                      {reviewerError}
                    </p>
                  )}
                </div>
              </>
            )}

            <div role="separator" className={SEPARATOR} />
            <button
              type="button"
              role="menuitem"
              tabIndex={-1}
              aria-disabled={signedIn ? undefined : true}
              className={cx(ITEM, signedIn ? 'text-danger' : 'cursor-not-allowed text-ink-tertiary')}
              onClick={() => {
                if (!signedIn) return;
                close();
                signOut();
              }}
            >
              <LogOut aria-hidden="true" className="size-4" strokeWidth={1.75} />
              {t('menu.logout')}
            </button>
          </div>
        )}
      </div>
      {/* Outside the menu's root, so the dialog's keys and focus never reach the menu's handlers. */}
      <JoinReviewDialog open={joining} onOpenChange={setJoining} />
    </>
  );
}
