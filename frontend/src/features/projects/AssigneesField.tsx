import { Plus, X } from 'lucide-react';
import { useState } from 'react';
import { Button } from '../../components/Button.tsx';
import { TextField } from '../../components/Field.tsx';
import { IconButton } from '../../components/IconButton.tsx';
import { FIELD_LABEL } from '../../components/Select.tsx';
import { Skeleton } from '../../components/Skeleton.tsx';
import { t } from '../../i18n/messages.ts';
import { cx } from '../../utils/classNames.ts';

/** The rule of the reviewer names people sign in with, so an assigned user can be @mentioned. */
const NAME = /^[A-Za-z][A-Za-z0-9_]{0,31}$/;
const MAX = 20;

interface AssigneesFieldProps {
  value: string[];
  onChange: (names: string[]) => void;
  suggestions?: string[];
  /** The suggestions are still loading: their row shows grey names. */
  suggestionsLoading?: boolean;
}

/**
 * The users assigned to a project: their names as chips with a remove button, a field to type a
 * name (Enter, a comma or Add adds it) and the reviewers who have signed in before as one-tap
 * suggestions. Names follow the sign-in rule: a letter, then letters, numbers or _.
 */
export function AssigneesField({ value, onChange, suggestions = [], suggestionsLoading = false }: AssigneesFieldProps) {
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const chosen = new Set(value.map((name) => name.toLowerCase()));
  const offered = suggestions.filter((name) => !chosen.has(name.toLowerCase())).slice(0, 8);

  const add = (raw: string) => {
    const name = raw.trim();
    if (!name) return true;
    if (!NAME.test(name)) {
      setError(t('Use the name the person signs in with: a letter, then letters, numbers or _, no spaces, at most 32 characters.'));
      return false;
    }
    if (value.length >= MAX && !chosen.has(name.toLowerCase())) {
      setError(t('A project can have at most {count} assigned users.', { count: MAX }));
      return false;
    }
    if (!chosen.has(name.toLowerCase())) onChange([...value, name]);
    setText('');
    setError(null);
    return true;
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <TextField
          label={t('Assigned users')}
          value={text}
          onChange={(next) => {
            setText(next);
            setError(null);
          }}
          maxLength={32}
          autoComplete="off"
          placeholder={t('For example, Larissa')}
          hint={t('The people who check this project’s bills, by the name they sign in with.')}
          errorMessage={error ?? undefined}
          className="flex-1"
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ',') {
              event.preventDefault();
              add(text);
            } else if (event.key === 'Backspace' && !text && value.length) {
              onChange(value.slice(0, -1));
            } else {
              event.continuePropagation?.();
            }
          }}
          onBlur={() => {
            if (text.trim()) add(text);
          }}
        />
        {/* An invisible copy of the label keeps Add level with the field, whatever shows under it. */}
        <div className="flex flex-col gap-1">
          <span aria-hidden="true" className={cx(FIELD_LABEL, 'invisible')}>
            {t('Add')}
          </span>
          <Button icon={Plus} onPress={() => add(text)} isDisabled={!text.trim()}>
            {t('Add')}
          </Button>
        </div>
      </div>
      {value.length > 0 && (
        <ul aria-label={t('Assigned users')} className="flex flex-wrap gap-2">
          {value.map((name) => (
            <li key={name} className="inline-flex items-center rounded-full border border-hairline bg-surface-muted pl-3 text-callout font-medium text-ink">
              {name}
              <IconButton icon={X} label={t('Remove {name}', { name })} className="rounded-full" onPress={() => onChange(value.filter((other) => other !== name))} />
            </li>
          ))}
        </ul>
      )}
      {suggestionsLoading && (
        // The names load: their row keeps its place, so the buttons under the form do not move.
        <div aria-hidden="true" className="flex min-h-11 flex-wrap items-center gap-4">
          <span className="text-caption text-ink-secondary">{t('Signed in before:')}</span>
          {['w-14', 'w-16', 'w-14', 'w-20'].map((width, index) => (
            <Skeleton key={index} className={`h-3.5 ${width}`} />
          ))}
        </div>
      )}
      {!suggestionsLoading && offered.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-caption text-ink-secondary">{t('Signed in before:')}</span>
          {offered.map((name) => (
            <Button key={name} variant="ghost" icon={Plus} onPress={() => add(name)} aria-label={t('Assign {name}', { name })}>
              {name}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
