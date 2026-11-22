import { Check } from 'lucide-react';
import { useId } from 'react';
import { ToggleButton } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { formatCount } from '../utils/format.ts';
import { HIT_TARGET } from './hitTarget.ts';
import type { ElementType, ReactNode } from 'react';

/**
 * Classes of a filter chip, selected or not. The weight of its text stays the same, so a chip
 * keeps its width when it is selected.
 */
export function chipClassName({ isSelected }: { isSelected: boolean }) {
  return cx(
    'state-layer inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-lg border px-3 text-callout transition-colors',
    HIT_TARGET,
    isSelected ? 'border-accent bg-accent-subtle text-accent-strong' : 'border-hairline-strong bg-surface text-ink-secondary hover:text-ink',
  );
}

interface ChipProps {
  selected: boolean;
  onChange: (selected: boolean) => void;
  icon?: ElementType;
  iconClassName?: string;
  count?: number;
  mono?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * One toggle chip (React Aria ToggleButton, aria-pressed) with an optional count. Selected, it
 * shows a check mark in place of its icon; a chip without an icon keeps the check mark's room as
 * two narrow spaces around its label instead, so selecting it never changes its width.
 */
export function Chip({
  selected,
  onChange,
  icon: Icon,
  iconClassName,
  count,
  mono = false,
  className,
  children,
}: ChipProps) {
  return (
    <ToggleButton isSelected={selected} onChange={onChange} className={(state) => cx(chipClassName(state), className)}>
      {selected && <Check aria-hidden="true" className="size-3.5 shrink-0" strokeWidth={2.25} />}
      {!selected && Icon && <Icon aria-hidden="true" className={cx('size-3.5 shrink-0', iconClassName)} strokeWidth={2} />}
      {/* 4 + 6 (gap) + 6 (gap) + 4 px: the 14 px check mark and its 6 px gap. */}
      {!selected && !Icon && <span aria-hidden="true" className="w-1 shrink-0" />}
      <span className={cx('truncate', mono && 'font-mono text-caption')}>{children}</span>
      {count !== undefined && ' '}
      {count !== undefined && (
        <span className={cx('tabular-nums', selected ? 'text-accent-strong' : 'text-ink-tertiary')}>{formatCount(count)}</span>
      )}
      {!selected && !Icon && <span aria-hidden="true" className="w-1 shrink-0" />}
    </ToggleButton>
  );
}

interface FilterChipsProps {
  label: string;
  options: {
      value: string;
      label: string;
      icon?: ElementType;
      iconClassName?: string;
      mono?: boolean;
      count?: number;
    }[];
  selected: string[];
  onChange: (selected: string[]) => void;
}

/**
 * Multi-select filter as a group of toggle chips. Selecting several chips in one group means "any
 * of these". An option's optional `count` is shown after its label.
 */
export function FilterChips({ label, options, selected, onChange }: FilterChipsProps) {
  const labelId = useId();
  const toggle = (value: string) => {
    onChange(selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]);
  };
  return (
    <div role="group" aria-labelledby={labelId} className="flex flex-wrap items-center gap-x-1.5 gap-y-2">
      <span id={labelId} className="w-32 shrink-0 text-caption font-medium text-ink-secondary">
        {label}
      </span>
      {options.map((option) => (
        <Chip
          key={option.value}
          selected={selected.includes(option.value)}
          onChange={() => toggle(option.value)}
          icon={option.icon}
          iconClassName={option.iconClassName}
          mono={option.mono}
          count={option.count}
        >
          {option.label}
        </Chip>
      ))}
    </div>
  );
}
