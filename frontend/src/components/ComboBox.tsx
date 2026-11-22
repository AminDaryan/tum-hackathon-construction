import { ChevronDown } from 'lucide-react';
import { Button as AriaButton, ComboBox as AriaComboBox, Input, Label, ListBox, Popover, Text } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { INPUT_CLASSES } from './Field.tsx';
import { HIT_HEIGHT } from './hitTarget.ts';
import { FIELD_LABEL, OptionItem, POPOVER } from './Select.tsx';
import { t } from '../i18n/messages.ts';

interface ComboBoxProps {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
  disabled?: boolean;
  hideLabel?: boolean;
  emptyText?: string;
  className?: string;
}

/**
 * Combobox (React Aria): a text input that filters a list of options as the user types, with
 * arrow keys, Enter to choose and Escape to close. Use it instead of Select for long lists (files,
 * positions, people). `value` is the chosen option's value, '' for none.
 */
export function ComboBox({
  label,
  value,
  options,
  onChange,
  placeholder,
  hint,
  disabled = false,
  hideLabel = false,
  emptyText,
  className,
}: ComboBoxProps) {
  return (
    <AriaComboBox
      selectedKey={value || null}
      onSelectionChange={(key) => onChange(key === null ? '' : String(key))}
      isDisabled={disabled}
      menuTrigger="focus"
      className={cx('group flex min-w-0 flex-col gap-1', className)}
    >
      <Label className={cx(FIELD_LABEL, hideLabel && 'sr-only')}>{label}</Label>
      <div className="relative">
        <Input
          placeholder={placeholder}
          className={cx(INPUT_CLASSES, HIT_HEIGHT, 'pr-10')}
        />
        <AriaButton className="absolute right-0 top-0 inline-flex h-full w-10 cursor-pointer items-center justify-center text-ink-tertiary hover:text-ink">
          <ChevronDown aria-hidden="true" className="size-4" strokeWidth={1.75} />
        </AriaButton>
      </div>
      {hint && (
        <Text slot="description" className="text-caption text-ink-tertiary">
          {hint}
        </Text>
      )}
      <Popover className={cx(POPOVER, 'max-h-80')} offset={4}>
        <ListBox className="outline-none" renderEmptyState={() => <p className="px-2.5 py-2 text-callout text-ink-tertiary">{emptyText ?? t('No matches')}</p>}>
          {options.map((option) => (
            <OptionItem key={option.value} id={option.value} textValue={option.label}>
              {option.label}
            </OptionItem>
          ))}
        </ListBox>
      </Popover>
    </AriaComboBox>
  );
}
