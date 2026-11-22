import { getLocalTimeZone, parseDate } from '@internationalized/date';
import { intlLocale, t } from '../../i18n/messages.ts';
import type { FindingTask } from '../../services/apiTypes.ts';
import { isTaskOverdue, labelOf, TASK_TYPES } from './tasks.ts';

interface TaskSummaryProps {
  task?: FindingTask | null;
}

/** A task's owner, type and deadline for the risk list. */
export function TaskSummary({ task }: TaskSummaryProps) {
  if (!task) return null;
  return (
    <>
      {task.task_type && <span className="text-accent">{labelOf(TASK_TYPES, task.task_type)}</span>}
      <span>{task.assignee_name ? t('Assigned to {name}', { name: task.assignee_name }) : t('Unassigned')}</span>
      {task.due_date && (
        <time dateTime={task.due_date} className={isTaskOverdue(task) ? 'font-semibold text-danger' : undefined}>
          {t(isTaskOverdue(task) ? 'Overdue: {date}' : 'Due {date}', {
            date: parseDate(task.due_date).toDate(getLocalTimeZone()).toLocaleDateString(intlLocale(), { dateStyle: 'medium' }),
          })}
        </time>
      )}
    </>
  );
}
