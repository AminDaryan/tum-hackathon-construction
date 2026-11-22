/**
 * What the Clarifications list of a project shows, as plain functions over the clarifications of
 * `clarificationsService.ts`: who is asked, how far each is, and when its answer is due against
 * the day of the bid decision. Labels are English marked with
 * `msg`; render them with `t`. The texts the functions return are translated already.
 */
import { intlLocale, msg, t } from '../../i18n/messages.ts';
import { formatCount } from '../../utils/format.ts';
import type { BadgeTone } from '../../components/Badge.tsx';
import type { Clarification } from '../../services/clarificationsService.ts';

/** Who is asked. `sent` is how "sent" reads for that party. */
export const KINDS = Object.freeze<
  { value: Clarification['kind']; label: string; tone: BadgeTone; sent: string }[]
>([
  { value: 'bidder_question', label: msg('Bidder question'), tone: 'semantic', sent: msg('Sent') },
  { value: 'subcontractor', label: msg('Subcontractor'), tone: 'success', sent: msg('Waiting for reply') },
  { value: 'management', label: msg('Management'), tone: 'anomaly', sent: msg('On agenda') },
]);

export const STATUSES = Object.freeze<{ value: Clarification['status']; label: string }[]>([
  { value: 'draft', label: msg('Draft') },
  { value: 'sent', label: msg('Sent') },
  { value: 'answered', label: msg('Answered, not decided') },
  { value: 'decided', label: msg('Decided') },
]);

export const PHASES = Object.freeze<{ value: Clarification['phase']; label: string }[]>([
  { value: 'bid', label: msg('Bid phase') },
  { value: 'after_award', label: msg('After award') },
]);

const DAY_MS = 24 * 60 * 60 * 1000;

export function kindOf(value: string) {
  return KINDS.find((kind) => kind.value === value) ?? KINDS[0];
}

/**
 * "Draft", "Waiting for reply", "Answered, not decided": the status in the words of its party. A
 * question the app suggested that nobody has saved yet (no id) is "Suggested", not a draft.
 */
export function statusText(item: Pick<Clarification, 'kind' | 'status'> & { clarification_id?: string | null }): string {
  if (item.clarification_id === null) return t('Suggested');
  if (item.status === 'sent') return t(kindOf(item.kind).sent);
  return t(STATUSES.find((status) => status.value === item.status)?.label ?? item.status);
}

export function isOpen(item: Pick<Clarification, 'status'>): boolean {
  return item.status !== 'decided';
}

/** A `YYYY-MM-DD` day as local midnight (`new Date(iso)` would be UTC, a day off west of it). */
function parseDay(iso: string | null | undefined): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? '');
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
}

/** Whole days from `today` to the day `iso`: 0 today, negative once it has passed. */
export function daysUntil(iso: string | null | undefined, today = new Date()): number | null {
  const day = parseDay(iso);
  if (!day) return null;
  const from = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((day.getTime() - from.getTime()) / DAY_MS);
}

/** "Dec 4", or "Thu, Dec 3" with the weekday, in the UI language like the rest of the app. */
export function formatDay(iso: string | null | undefined, { weekday = false }: { weekday?: boolean } = {}): string {
  const day = parseDay(iso);
  const options: Intl.DateTimeFormatOptions = weekday ? { weekday: 'short', day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short' };
  return day ? new Intl.DateTimeFormat(intlLocale(), options).format(day) : '';
}

/** "Nov 21", the day an email was first sent (an ISO time), in the UI language. */
export function formatSent(iso: string | null | undefined): string {
  const time = iso ? new Date(iso) : null;
  return time && !Number.isNaN(time.getTime())
    ? new Intl.DateTimeFormat(intlLocale(), { day: 'numeric', month: 'short' }).format(time)
    : '';
}

/**
 * How close the answer's day is: "in 13 days", "today", "2 days overdue", or "cutoff" when it is
 * the day of the bid decision. `urgent` marks what cannot slip. Null without a day, or once decided.
 */
export function dueNote(
  item: Pick<Clarification, 'due' | 'status'>,
  cutoff: string | null,
  today = new Date(),
): { text: string; urgent: boolean } | null {
  const days = daysUntil(item.due, today);
  if (days === null || !isOpen(item)) return null;
  if (days < 0) return { text: t(days === -1 ? '1 day overdue' : '{count} days overdue', { count: formatCount(-days) }), urgent: true };
  if (cutoff && item.due === cutoff) return { text: t('cutoff'), urgent: true };
  if (days === 0) return { text: t('today'), urgent: true };
  return { text: t(days === 1 ? 'in 1 day' : 'in {count} days', { count: formatCount(days) }), urgent: false };
}
