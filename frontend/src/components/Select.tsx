import { Check, ChevronDown } from 'lucide-react';
import {
  Button as AriaButton,
  Select as AriaSelect,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  SelectValue,
  Text,
  type Key,
} from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { HIT_HEIGHT } from './hitTarget.ts';
import type { ReactNode } from 'react';

/** React Aria keys cannot be the empty string; '' means "any" or "none" throughout the app. */
const EMPTY_KEY = '__empty__';
const toKey = (value: string) => (value === '' ? EMPTY_KEY : value);
const fromKey = (key: Key) => (key === EMPTY_KEY ? '' : String(key));

/** Shared look of a field's control box: text fields, selects and comboboxes. */
export const FIELD_CONTROL =
  'w-full rounded-md border border-control-border bg-surface text-callout text-ink shadow-control transition-colors ' +
  'hover:border-ink-tertiary data-disabled:cursor-not-allowed data-disabled:opacity-50';

/** Label above a field. */
export const FIELD_LABEL = 'text-caption font-medium text-ink-secondary';

/** Floating list surface for select, combobox and menu popovers; it grows from its trigger and fades in and out. */
export const POPOVER =
  'min-w-(--trigger-width) overflow-auto rounded-lg border border-hairline-strong bg-surface p-1 shadow-popover outline-none ' +
  'origin-(--trigger-anchor-point) data-entering:animate-[popover-in_150ms_var(--ease-standard)] ' +
  'data-exiting:animate-[popover-out_120ms_var(--ease-standard)_forwards]';

/** One option row in a select, combobox or menu. */
export function optionClassName({
  isFocused,
  isSelected,
  isDisabled,
}: { isFocused?: boolean; isSelected?: boolean; isDisabled?: boolean } = {}) {
  return cx(
    'flex min-h-8 cursor-pointer items-center gap-2 rounded-md px-2.5 text-callout text-ink outline-none pointer-coarse:min-h-11',
    isFocused && 'bg-state-hover',
    isSelected && 'font-medium text-accent-strong',
    isDisabled && 'text-ink-tertiary',
  );
}

interface OptionItemProps {
  id: string;
  textValue?: string;
  children: ReactNode;
}

/** An option with a check mark when selected. */
export function OptionItem({ id, textValue, children }: OptionItemProps) {
  return (
    <ListBoxItem id={id} textValue={textValue} className={optionClassName}>
      {({ isSelected }) => (
        <>
          <span className="min-w-0 flex-1 truncate">{children}</span>
          {isSelected && <Check aria-hidden="true" className="size-4 shrink-0 text-accent" strokeWidth={2} />}
        </>
      )}
    </ListBoxItem>
  );
}

interface SelectProps {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  hideLabel?: boolean;
  hint?: string;
  disabled?: boolean;
  className?: string;
}

/**
 * Labelled select (React Aria): a button showing the value that opens a listbox popover, with
 * type-ahead, arrow keys, Home/End and Escape. The trigger exposes the label as its accessible
 * name; a hidden native select keeps form submission and autofill working.
 *
 * The control is at least as wide as its widest option, so it keeps its width whichever option
 * is chosen.
 */
export function Select({
  label,
  value,
  options,
  onChange,
  hideLabel = false,
  hint,
  disabled = false,
  className,
}: SelectProps) {
  return (
    <AriaSelect
      value={toKey(value)}
      onChange={(key) => key !== null && onChange(fromKey(key))}
      isDisabled={disabled}
      className={cx('flex min-w-0 flex-col gap-1', className)}
    >
      <Label className={cx(FIELD_LABEL, hideLabel && 'sr-only')}>{label}</Label>
      <div className="grid min-w-0 grid-cols-1">
        <AriaButton
          className={cx(
            FIELD_CONTROL,
            HIT_HEIGHT,
            'col-start-1 row-start-1 flex min-w-0 cursor-pointer items-center gap-2 pl-2.5 pr-2 text-left data-pressed:border-accent',
          )}
        >
          <SelectValue className="min-w-0 flex-1 truncate" />
          <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-ink-tertiary" strokeWidth={1.75} />
        </AriaButton>
        {/* Every option, invisible and flat under the control (with its padding and chevron), sets its width. */}
        <span aria-hidden="true" className="invisible col-start-1 row-start-1 flex h-0 min-w-0 gap-2 overflow-hidden border-x pl-2.5 pr-2 text-callout">
          <span className="grid">
            {options.map((option) => (
              <span key={toKey(option.value)} className="col-start-1 row-start-1 whitespace-nowrap">
                {option.label}
              </span>
            ))}
          </span>
          <span className="w-4 shrink-0" />
        </span>
      </div>
      {hint && (
        <Text slot="description" className="text-caption text-ink-tertiary">
          {hint}
        </Text>
      )}
      <Popover className={cx(POPOVER, 'max-h-80')} offset={4}>
        <ListBox className="outline-none">
          {options.map((option) => (
            <OptionItem key={toKey(option.value)} id={toKey(option.value)} textValue={option.label}>
              {option.label}
            </OptionItem>
          ))}
        </ListBox>
      </Popover>
    </AriaSelect>
  );
}
