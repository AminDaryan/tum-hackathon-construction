import type { LucideIcon } from 'lucide-react';
import { ToggleButton, ToggleButtonGroup } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { HIT_TARGET } from './hitTarget.ts';

interface SegmentedControlProps<Value extends string> {
  /** The control's name, when no visible label names it through `labelledBy`. */
  label?: string;
  /** The id of the visible label that names the control. */
  labelledBy?: string;
  describedBy?: string;
  value: Value;
  options: readonly { value: Value; label: string; icon?: LucideIcon }[];
  onChange: (value: Value) => void;
}

/**
 * One choice among a few, as a segmented control: the options side by side in one track, the
 * chosen one raised. Announced as radio buttons; the arrow keys move between them.
 */
export function SegmentedControl<Value extends string>({
  label,
  labelledBy,
  describedBy,
  value,
  options,
  onChange,
}: SegmentedControlProps<Value>) {
  return (
    <ToggleButtonGroup
      aria-label={label}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      selectionMode="single"
      disallowEmptySelection
      selectedKeys={[value]}
      onSelectionChange={(keys) => {
        const chosen = options.find((option) => keys.has(option.value));
        if (chosen) onChange(chosen.value);
      }}
      className="inline-flex max-w-full flex-wrap gap-0.5 rounded-md bg-state-selected p-0.5"
    >
      {options.map(({ value: id, label: optionLabel, icon: Icon }) => (
        <ToggleButton
          key={id}
          id={id}
          className={({ isSelected }) =>
            cx(
              'flex cursor-pointer items-center justify-center gap-1.5 rounded-sm px-3 text-callout font-medium transition-colors',
              HIT_TARGET,
              isSelected ? 'bg-surface text-ink shadow-control' : 'text-ink-secondary hover:text-ink',
            )
          }
        >
          {Icon && <Icon aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />}
          {optionLabel}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}
