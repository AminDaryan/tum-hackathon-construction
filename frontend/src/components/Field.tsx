import { Search, X } from 'lucide-react';
import {
  Button as AriaButton,
  Input,
  Label,
  SearchField as AriaSearchField,
  Text,
  TextArea,
  TextField as AriaTextField,
  type SearchFieldProps as AriaSearchFieldProps,
  type TextFieldProps as AriaTextFieldProps,
} from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { HIT_HEIGHT } from './hitTarget.ts';
import { FIELD_CONTROL, FIELD_LABEL } from './Select.tsx';
import { t } from '../i18n/messages.ts';
import type { Ref } from 'react';

/** A text input's box: text fields, search fields and comboboxes. */
export const INPUT_CLASSES = cx(
  FIELD_CONTROL,
  'px-2.5 placeholder:text-ink-tertiary outline-none data-focused:border-accent data-focus-visible:outline-2 data-focus-visible:outline-offset-1 data-focus-visible:outline-focus',
  'data-invalid:border-danger',
);

interface TextFieldProps extends Omit<AriaTextFieldProps, 'className' | 'children' | 'value' | 'onChange'> {
  label: string;
  value?: string;
  onChange?: (value: string) => void;
  hideLabel?: boolean;
  hint?: string;
  errorMessage?: string;
  placeholder?: string;
  multiline?: boolean;
  rows?: number;
  inputRef?: Ref<HTMLInputElement & HTMLTextAreaElement>;
  type?: string;
  inputClassName?: string;
  className?: string;
}

/**
 * Labelled text field (React Aria): label, optional hint and validation message are wired to the
 * input through aria-labelledby and aria-describedby. `multiline` renders a text area. Extra props
 * (maxLength, autoComplete, inputMode, isRequired, autoFocus, ...) go to the field.
 */
export function TextField({
  label,
  value,
  onChange,
  hideLabel = false,
  hint,
  errorMessage,
  placeholder,
  multiline = false,
  rows,
  inputRef,
  type,
  inputClassName,
  className,
  ...rest
}: TextFieldProps) {
  return (
    <AriaTextField
      value={value}
      onChange={onChange}
      type={type}
      isInvalid={Boolean(errorMessage) || undefined}
      className={cx('flex min-w-0 flex-col gap-1', className)}
      {...rest}
    >
      <Label className={cx(FIELD_LABEL, hideLabel && 'sr-only')}>{label}</Label>
      {multiline ? (
        <TextArea ref={inputRef} rows={rows} placeholder={placeholder} className={cx(INPUT_CLASSES, 'min-h-16 resize-y py-1.5', inputClassName)} />
      ) : (
        <Input ref={inputRef} placeholder={placeholder} className={cx(INPUT_CLASSES, HIT_HEIGHT, inputClassName)} />
      )}
      {hint && (
        <Text slot="description" className="text-caption text-ink-tertiary">
          {hint}
        </Text>
      )}
      {errorMessage && (
        <Text slot="errorMessage" elementType="p" role="alert" className="text-caption text-danger">
          {errorMessage}
        </Text>
      )}
    </AriaTextField>
  );
}

interface SearchFieldProps extends Omit<AriaSearchFieldProps, 'className' | 'children' | 'value' | 'onChange'> {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  showLabel?: boolean;
  className?: string;
}

/**
 * Search field (React Aria): a search icon, a clear button while it has text, and Escape clears
 * it. The label is visually hidden unless `showLabel`.
 */
export function SearchField({
  label,
  value,
  onChange,
  placeholder,
  showLabel = false,
  className,
  ...rest
}: SearchFieldProps) {
  return (
    <AriaSearchField value={value} onChange={onChange} className={cx('group flex min-w-0 flex-col gap-1', className)} {...rest}>
      <Label className={cx(FIELD_LABEL, !showLabel && 'sr-only')}>{label}</Label>
      <div className="relative">
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-tertiary"
          strokeWidth={1.75}
        />
        <Input
          placeholder={placeholder}
          className={cx(INPUT_CLASSES, HIT_HEIGHT, 'pl-9 pr-10 [&::-webkit-search-cancel-button]:hidden')}
        />
        {value && (
          <AriaButton
            aria-label={t('Clear search')}
            className="absolute right-0 top-0 inline-flex h-full w-10 cursor-pointer items-center justify-center rounded-md text-ink-tertiary hover:text-ink"
          >
            <X aria-hidden="true" className="size-4" strokeWidth={1.75} />
          </AriaButton>
        )}
      </div>
    </AriaSearchField>
  );
}
