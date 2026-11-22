import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react';
import { parseDate } from '@internationalized/date';
import { useState } from 'react';
import {
  Button as AriaButton,
  Calendar,
  CalendarCell,
  CalendarGrid,
  DateInput,
  DatePicker,
  DateSegment,
  Dialog as AriaDialog,
  FieldError,
  Group,
  Heading,
  Label,
  Popover,
} from 'react-aria-components';
import { Button } from '../../components/Button.tsx';
import { FIELD_CONTROL, FIELD_LABEL, POPOVER, Select } from '../../components/Select.tsx';
import { HIT_HEIGHT, HIT_SQUARE } from '../../components/hitTarget.ts';
import { t } from '../../i18n/messages.ts';
import type { Reviewer, TaskInput, TaskType } from '../../services/apiTypes.ts';
import { cx } from '../../utils/classNames.ts';
import { TASK_TYPES } from './tasks.ts';
import type { DateValue } from 'react-aria-components';

// The due dates the server takes. A year is typed digit by digit (2, 20, 202, 2026): the
// partial years fall outside, so only the finished date is saved.
const EARLIEST_DUE_DATE = parseDate('2000-01-01');
const LATEST_DUE_DATE = parseDate('2100-12-31');

interface TaskFieldsProps {
  task: TaskInput;
  reviewers: Reviewer[];
  isDisabled: boolean;
  onSave: (change: Partial<TaskInput>) => void;
}

/** A finding's task: assignee, type and due date, each saved as soon as it changes. */
export function TaskFields({ task, reviewers, isDisabled, onSave }: TaskFieldsProps) {
  // A typed due date that is not saved (yet), shown until the saved one changes.
  const [dueDraft, setDueDraft] = useState<{ saved: string | null; value: DateValue | null } | null>(null);
  return (
    <div role="group" aria-label={t('Task')} className="mb-3 grid grid-cols-2 gap-2 max-sm:grid-cols-1">
      <Select
        label={t('Assignee')}
        value={task.assignee ?? ''}
        disabled={isDisabled}
        options={[
          { value: '', label: t('Unassigned') },
          ...reviewers.map((person) => ({
            value: person.handle,
            label: person.name,
          })),
        ]}
        onChange={(value) => onSave({ assignee: value || null })}
      />
      <Select
        label={t('Type')}
        value={task.task_type ?? ''}
        disabled={isDisabled}
        options={[{ value: '', label: t('No type') }, ...TASK_TYPES.map((option) => ({ ...option, label: t(option.label) }))]}
        onChange={(value) => onSave({ task_type: (value || null) as TaskType | null })}
      />
      <DatePicker
        value={
          dueDraft && dueDraft.saved === (task.due_date ?? null)
            ? dueDraft.value
            : task.due_date ? parseDate(task.due_date) : null
        }
        minValue={EARLIEST_DUE_DATE}
        maxValue={LATEST_DUE_DATE}
        validationBehavior="aria"
        onChange={(value) => {
          setDueDraft({ saved: task.due_date ?? null, value });
          if (value && value.compare(EARLIEST_DUE_DATE) >= 0 && value.compare(LATEST_DUE_DATE) <= 0) {
            onSave({ due_date: value.toString() });
          }
        }}
        isDisabled={isDisabled}
        className="flex min-w-0 flex-col gap-1"
      >
        <Label className={FIELD_LABEL}>{t('Due date')}</Label>
        <Group className={cx(FIELD_CONTROL, HIT_HEIGHT, 'flex items-center gap-1 pl-2 focus-within:outline-2 focus-within:outline-focus')}>
          <DateInput className="flex min-w-0 flex-1 py-2">
            {(segment) => <DateSegment segment={segment} className="rounded-sm px-0.5 outline-none data-focused:bg-accent data-focused:text-on-accent data-placeholder:text-ink-tertiary" />}
          </DateInput>
          <AriaButton aria-label={t('Choose due date')} className={cx(HIT_SQUARE, 'flex shrink-0 items-center justify-center rounded-md hover:bg-state-hover data-focus-visible:outline-2 data-focus-visible:outline-focus')}>
            <CalendarDays aria-hidden="true" className="size-4" />
          </AriaButton>
        </Group>
        <FieldError className="text-caption text-danger">{t('Enter a date between 2000 and 2100.')}</FieldError>
        <Popover placement="bottom end" className={cx(POPOVER, 'p-3')}>
          <AriaDialog className="outline-none">
            <Calendar>
              <header className="mb-2 flex items-center justify-between gap-3">
                <AriaButton slot="previous" aria-label={t('Previous month')} className="flex size-9 items-center justify-center rounded-md hover:bg-state-hover"><ChevronLeft className="size-4" /></AriaButton>
                <Heading className="text-callout font-semibold" />
                <AriaButton slot="next" aria-label={t('Next month')} className="flex size-9 items-center justify-center rounded-md hover:bg-state-hover"><ChevronRight className="size-4" /></AriaButton>
              </header>
              <CalendarGrid>
                {(date) => <CalendarCell date={date} className="flex size-9 cursor-pointer items-center justify-center rounded-md text-callout outline-none hover:bg-state-hover data-selected:bg-accent data-selected:text-on-accent data-focus-visible:ring-2 data-focus-visible:ring-focus data-outside-month:text-ink-tertiary" />}
              </CalendarGrid>
            </Calendar>
          </AriaDialog>
        </Popover>
      </DatePicker>
      {task.due_date && (
        <Button variant="link" isDisabled={isDisabled} onPress={() => onSave({ due_date: null })}>
          {t('Clear due date')}
        </Button>
      )}
    </div>
  );
}
