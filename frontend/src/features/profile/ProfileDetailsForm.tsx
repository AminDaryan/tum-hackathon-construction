import { RotateCcw, Save } from 'lucide-react';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Button } from '../../components/Button.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useI18n } from '../../i18n/useI18n.ts';
import type { UserAccount } from '../../services/apiTypes.ts';
import type { ProfileChanges } from '../../services/usersService.ts';
import { cx } from '../../utils/classNames.ts';
import { describeError } from '../../utils/errors.ts';

type DetailField = keyof ProfileChanges;
type DetailValues = Record<DetailField, string>;
/** What is wrong with the form, by field (i18n keys). */
type Problems = Partial<Record<DetailField, string>>;

const FIELDS: {
  id: DetailField;
  label: string;
  maxLength: number;
  autoComplete: string;
  required?: boolean;
  type?: string;
}[] = [
  { id: 'first_name', label: 'profile.firstName', maxLength: 80, autoComplete: 'given-name', required: true },
  { id: 'last_name', label: 'profile.lastName', maxLength: 80, autoComplete: 'family-name' },
  { id: 'email', label: 'profile.email', maxLength: 254, autoComplete: 'email', type: 'email' },
  { id: 'job_title', label: 'profile.jobTitle', maxLength: 120, autoComplete: 'organization-title' },
  { id: 'phone', label: 'profile.phone', maxLength: 40, autoComplete: 'tel', type: 'tel' },
];
const EMAIL = /^[^@\s]+@[^@\s]+$/;
const PHONE = /^[0-9+()./ -]*$/;
const INPUT =
  'h-11 w-full rounded-md border bg-surface px-2.5 text-callout text-ink transition-colors hover:border-ink-tertiary disabled:opacity-50 pointer-coarse:h-12';

function valuesOf(account: UserAccount): DetailValues {
  return Object.fromEntries(FIELDS.map((field) => [field.id, account[field.id] ?? ''])) as DetailValues;
}

/** What is wrong with the form, by field (texts are i18n keys). */
function problemsOf(values: DetailValues, firstNameMissing: string): Problems {
  const problems: Problems = {};
  if (!values.first_name.trim()) problems.first_name = firstNameMissing;
  if (values.email.trim() && !EMAIL.test(values.email.trim())) problems.email = 'profile.emailInvalid';
  if (!PHONE.test(values.phone.trim())) problems.phone = 'profile.phoneInvalid';
  return problems;
}

interface ProfileDetailsFormProps<TResult> {
  account: UserAccount;
  /** Saves the changed fields only. */
  save: (changes: ProfileChanges, signal: AbortSignal) => Promise<TResult>;
  onSaved: (result: TResult) => void;
  /**
   * Given when an administrator edits someone's account: Cancel closes the form, the texts speak
   * of the user instead of "you", and the browser does not fill in the administrator's own details.
   */
  onCancel?: () => void;
}

/** A user's details, editable: first and last name, email, job title, phone. */
export function ProfileDetailsForm<TResult>({ account, save, onSaved, onCancel }: ProfileDetailsFormProps<TResult>) {
  const { t } = useI18n();
  const baseId = useId();
  const refs = useRef<Partial<Record<DetailField, HTMLInputElement | null>>>({});
  const [values, setValues] = useState(() => valuesOf(account));
  const [problems, setProblems] = useState<Problems>({});
  const [saved, setSaved] = useState(false);
  const saving = useAsyncAction((signal, changes: ProfileChanges) => save(changes, signal));
  const forOther = onCancel !== undefined;

  useEffect(() => {
    setValues(valuesOf(account));
  }, [account]);

  const original = valuesOf(account);
  const dirty = FIELDS.some((field) => values[field.id] !== original[field.id]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const found = problemsOf(values, forOther ? 'users.nameMissing' : 'profile.firstNameMissing');
    setProblems(found);
    const first = FIELDS.find((field) => found[field.id]);
    if (first) {
      refs.current[first.id]?.focus();
      return;
    }
    const changes = Object.fromEntries(
      FIELDS.filter((field) => values[field.id] !== original[field.id]).map((field) => [field.id, values[field.id].trim()]),
    );
    const result = await saving.execute(changes);
    if (result !== undefined) {
      setSaved(true);
      onSaved(result);
    }
  };

  return (
    <form noValidate onSubmit={submit} aria-label={t('profile.details.title')} className="flex flex-col gap-5">
      <div className="grid gap-4 sm:grid-cols-2">
        {FIELDS.map((field) => {
          const inputId = `${baseId}-${field.id}`;
          const errorId = `${inputId}-error`;
          const problem = problems[field.id];
          return (
            <div key={field.id} className="flex min-w-0 flex-col gap-1">
              <label htmlFor={inputId} className="text-caption font-medium text-ink-secondary">
                {t(field.label)}
                {field.required && <span aria-hidden="true"> *</span>}
              </label>
              <input
                ref={(node) => {
                  refs.current[field.id] = node;
                }}
                id={inputId}
                type={field.type ?? 'text'}
                value={values[field.id]}
                maxLength={field.maxLength}
                autoComplete={forOther ? 'off' : field.autoComplete}
                required={field.required}
                aria-invalid={problem ? true : undefined}
                aria-describedby={problem ? errorId : undefined}
                onChange={(event) => {
                  const { value } = event.target;
                  setValues((current) => ({ ...current, [field.id]: value }));
                  setSaved(false);
                }}
                className={cx(INPUT, problem ? 'border-danger' : 'border-control-border')}
              />
              {problem && (
                <p id={errorId} className="text-caption text-danger">
                  {t(problem)}
                </p>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" icon={Save} loading={saving.pending} isDisabled={!dirty}>
          {t('profile.save')}
        </Button>
        {forOther ? (
          <Button variant="ghost" isDisabled={saving.pending} onPress={onCancel}>
            {t('users.cancel')}
          </Button>
        ) : (
          <>
            <Button
              variant="ghost"
              icon={RotateCcw}
              isDisabled={!dirty || saving.pending}
              onPress={() => {
                setValues(original);
                setProblems({});
              }}
            >
              {t('profile.reset')}
            </Button>
            <p role="status" className="text-callout text-ink-secondary">
              {saved && !dirty ? t('profile.saved') : ''}
            </p>
          </>
        )}
      </div>
      {saving.error && (
        <p role="alert" className="text-callout text-danger">
          {t(forOther ? 'users.saveFailed' : 'profile.saveFailed', { message: describeError(saving.error).message })}
        </p>
      )}
    </form>
  );
}
