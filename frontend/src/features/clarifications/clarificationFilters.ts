/** The search and filters above a project's clarifications, without React. */
import { msg } from '../../i18n/messages.ts';
import type { ClarificationQuery } from '../../services/clarificationsService.ts';

export interface ClarificationFilters {
  /** words found in the item, its bill's name, its recipient or its answer */
  search: string;
  /** '' for both phases */
  phase: '' | NonNullable<ClarificationQuery['phase']>;
  /** '' for every type */
  kind: '' | NonNullable<ClarificationQuery['kind']>;
  /** '' for every status; 'suggested' for a question nobody has saved yet */
  status: '' | NonNullable<ClarificationQuery['status']>;
  /** 'this_week': open and needed within a week, or overdue; '' for any day */
  due: '' | 'this_week';
}

export const NO_CLARIFICATION_FILTERS: Readonly<ClarificationFilters> = Object.freeze({
  search: '',
  phase: '',
  kind: '',
  status: '',
  due: '',
});

export const STATUS_FILTERS = Object.freeze<{ value: NonNullable<ClarificationQuery['status']>; label: string }[]>([
  { value: 'suggested', label: msg('Suggested') },
  { value: 'draft', label: msg('Draft') },
  { value: 'sent', label: msg('Sent') },
  { value: 'answered', label: msg('Answered, not decided') },
  { value: 'decided', label: msg('Decided') },
]);

/** An answer still to come counts as due "this week" from this many days ahead. */
const DUE_SOON_DAYS = 7;

export function hasClarificationFilters(filters: ClarificationFilters): boolean {
  return Object.values(filters).some((value) => value.trim() !== '');
}

/**
 * The filters as the request's parameters. "Due this week" asks for what is needed by the day a
 * week from `today` (local), which takes in what is overdue.
 */
export function clarificationQuery(
  filters: ClarificationFilters,
  today = new Date(),
): Omit<ClarificationQuery, 'offset' | 'limit'> {
  const { search, phase, kind, status, due } = filters;
  let dueBy: string | undefined;
  if (due === 'this_week') {
    const day = new Date(today.getFullYear(), today.getMonth(), today.getDate() + DUE_SOON_DAYS);
    const pad = (value: number) => String(value).padStart(2, '0');
    dueBy = `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
  }
  return {
    search: search.trim() || undefined,
    phase: phase || undefined,
    kind: kind || undefined,
    status: status || undefined,
    due_by: dueBy,
  };
}
