import { getLocalTimeZone, today } from '@internationalized/date';
import { msg, t } from '../../i18n/messages.ts';
import type { FindingTask, TaskStatus, TaskType } from '../../services/apiTypes.ts';

/** Fixed task vocabulary; the server accepts exactly these values. */
export const TASK_STATUSES = Object.freeze<{ value: TaskStatus; label: string }[]>([
  { value: 'todo', label: msg('To do') },
  { value: 'in_progress', label: msg('In progress') },
  { value: 'waiting', label: msg('Waiting') },
  { value: 'done', label: msg('Done') },
]);
export const TASK_TYPES = Object.freeze<{ value: TaskType; label: string }[]>([
  { value: 'check', label: msg('Check') },
  { value: 'fix', label: msg('Fix') },
  { value: 'ask_client', label: msg('Ask client') },
  { value: 'discussion', label: msg('Discussion') },
]);

export const labelOf = (list: readonly { value: string; label: string }[], value = '') =>
  t(list.find((option) => option.value === value)?.label ?? value);

/** An assigned task is overdue after its local calendar deadline, regardless of stored status. */
export function isTaskOverdue(task: Pick<FindingTask, 'due_date' | 'assignee'> | null | undefined): boolean {
  return Boolean(task?.due_date && task.assignee && task.due_date < today(getLocalTimeZone()).toString());
}
