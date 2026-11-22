import { ChevronDown } from 'lucide-react';
import { Button as AriaButton, ListBox, Popover, Select as AriaSelect, SelectValue } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { Badge, badgeClassName, type BadgeTone } from './Badge.tsx';
import { HIT_TARGET } from './hitTarget.ts';
import { OptionItem, POPOVER } from './Select.tsx';
import type { ElementType } from 'react';

export interface StatusOption<Value extends string> {
  value: Value;
  label: string;
  icon: ElementType;
  tone: BadgeTone;
}

interface StatusSelectProps<Value extends string> {
  /** the accessible name, such as "Status of Riverside" */
  label: string;
  value: Value;
  options: readonly StatusOption<Value>[];
  onChange: (value: Value) => void;
  /** nothing to change here (a viewer, one's own account): the badge alone */
  readOnly?: boolean;
  /** a change is being saved */
  disabled?: boolean;
}

/**
 * A status in a table row that can be changed there: the status badge (icon, label and colour)
 * with an arrow, which opens the statuses to choose from (React Aria Select: arrow keys,
 * type-ahead, Escape). The badge is as wide as the longest status, so the column stays put when
 * one changes, and its hit area is the control's full size. A press on it never opens the row.
 * Read-only, it is the plain badge.
 */
export function StatusSelect<Value extends string>({ label, value, options, onChange, readOnly = false, disabled = false }: StatusSelectProps<Value>) {
  const current = options.find((option) => option.value === value) ?? options[0];
  const Icon = current.icon;
  if (readOnly) {
    return (
      <Badge tone={current.tone} icon={current.icon}>
        {current.label}
      </Badge>
    );
  }
  return (
    <AriaSelect
      aria-label={label}
      value={current.value}
      onChange={(key) => {
        const next = options.find((option) => option.value === key);
        if (next && next.value !== current.value) onChange(next.value);
      }}
      isDisabled={disabled}
      className="inline-flex"
    >
      <AriaButton
        className={cx(
          'group inline-flex cursor-pointer items-center rounded-md text-left outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus data-disabled:cursor-wait',
          HIT_TARGET,
        )}
      >
        {/* Screen readers hear the label and the value; the badge is for the eye. */}
        <SelectValue className="sr-only" />
        <span aria-hidden="true" className={cx(badgeClassName(current.tone), 'transition-colors group-hover:border-ink-tertiary group-data-pressed:border-accent')}>
          <Icon aria-hidden="true" className="size-3.5 shrink-0" strokeWidth={2} />
          {/* Every label in one cell, the others invisible, so the badge is as wide as the longest. */}
          <span className="grid">
            {options.map((option) => (
              <span key={option.value} className={cx('col-start-1 row-start-1', option.value !== current.value && 'invisible')}>
                {option.label}
              </span>
            ))}
          </span>
          <ChevronDown aria-hidden="true" className="size-3.5 shrink-0" strokeWidth={2} />
        </span>
      </AriaButton>
      <Popover className={cx(POPOVER, 'min-w-40')} placement="bottom start" offset={4}>
        <ListBox className="outline-none">
          {options.map((option) => (
            <OptionItem key={option.value} id={option.value} textValue={option.label}>
              <span className="flex items-center gap-2">
                <option.icon aria-hidden="true" className="size-4 shrink-0 text-ink-tertiary" strokeWidth={1.75} />
                {option.label}
              </span>
            </OptionItem>
          ))}
        </ListBox>
      </Popover>
    </AriaSelect>
  );
}
