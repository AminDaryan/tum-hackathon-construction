import { RotateCcw } from 'lucide-react';
import { useId } from 'react';
import {
  CHOICES,
  DEFAULT_PREFERENCES,
  resetAccessibilityPreferences,
  setAccessibilityPreference,
  useAccessibilityPreferences,
  type AccessibilityPreferences,
} from '../../app/accessibility.ts';
import { Button } from '../../components/Button.tsx';
import { HIT_TARGET } from '../../components/hitTarget.ts';
import { SegmentedControl } from '../../components/SegmentedControl.tsx';
import { Section } from '../../components/Section.tsx';
import { useI18n } from '../../i18n/useI18n.ts';
import { cx } from '../../utils/classNames.ts';

interface ChoiceRowProps {
  label: string;
  description: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}

/** One choice among a few: its name and what it does at the start of the row, the choice at its end. */
function ChoiceRow({ label, description, value, options, onChange }: ChoiceRowProps) {
  const labelId = useId();
  const descriptionId = useId();
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
      <div className="min-w-0 flex-1 basis-64">
        <p id={labelId} className="text-callout font-medium text-ink">
          {label}
        </p>
        <p id={descriptionId} className="text-caption text-ink-secondary">
          {description}
        </p>
      </div>
      <SegmentedControl labelledBy={labelId} describedBy={descriptionId} value={value} options={options} onChange={onChange} />
    </div>
  );
}

interface SwitchProps {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

/** An on/off preference in a row like a choice: a checkbox announced as a switch. */
function Switch({ label, description, checked, onChange }: SwitchProps) {
  const id = useId();
  const descriptionId = useId();
  return (
    <div className="flex items-center justify-between gap-6 px-4 py-3">
      <div className="min-w-0">
        <label htmlFor={id} className="text-callout font-medium text-ink">
          {label}
        </label>
        <p id={descriptionId} className="text-caption text-ink-secondary">
          {description}
        </p>
      </div>
      <span className={cx('relative inline-flex min-w-11 shrink-0 items-center justify-center', HIT_TARGET)}>
        <input
          id={id}
          type="checkbox"
          role="switch"
          checked={checked}
          aria-describedby={descriptionId}
          onChange={(event) => onChange(event.target.checked)}
          className="peer absolute inset-0 z-10 cursor-pointer opacity-0"
        />
        <span
          aria-hidden="true"
          className={cx(
            'relative h-6 w-11 rounded-full border transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus',
            checked ? 'border-accent bg-accent' : 'border-control-border bg-surface-muted',
          )}
        >
          <span
            className={cx(
              'absolute top-0.5 size-[1.125rem] rounded-full shadow-control transition-transform',
              checked ? 'translate-x-[1.3rem] bg-on-accent' : 'translate-x-0.5 bg-ink-tertiary',
            )}
          />
        </span>
      </span>
    </div>
  );
}

/**
 * Settings, Accessibility: text size, contrast, motion, underlined links, reading spacing and a
 * strong focus ring, for this browser. Every change applies at once.
 */
export function AccessibilityPanel() {
  const { t } = useI18n();
  const preferences = useAccessibilityPreferences();
  const isDefault = Object.entries(DEFAULT_PREFERENCES).every(([key, value]) => preferences[key as keyof AccessibilityPreferences] === value);
  const set = (key: keyof AccessibilityPreferences) => (value: string | boolean) => setAccessibilityPreference(key, value);
  const choice = (key: 'textSize' | 'contrast' | 'motion') => ({
    label: t(`a11y.${key}`),
    description: t(`a11y.${key}.description`),
    value: preferences[key],
    options: CHOICES[key].map((value) => ({ value, label: t(`a11y.${key}.${value}`) })),
    onChange: set(key),
  });

  return (
    <>
      <Section
        title={t('a11y.title')}
        description={t('a11y.description')}
        actions={
          <Button icon={RotateCcw} isDisabled={isDefault} onPress={resetAccessibilityPreferences}>
            {t('a11y.reset')}
          </Button>
        }
      >
        <div className="divide-y divide-hairline">
          <ChoiceRow {...choice('textSize')} />
          <ChoiceRow {...choice('contrast')} />
          <ChoiceRow {...choice('motion')} />
        </div>
      </Section>
      <Section title={t('a11y.reading')} description={t('a11y.reading.description')}>
        <div className="divide-y divide-hairline">
          <Switch
            label={t('a11y.underlineLinks')}
            description={t('a11y.underlineLinks.description')}
            checked={preferences.underlineLinks}
            onChange={set('underlineLinks')}
          />
          <Switch
            label={t('a11y.readableText')}
            description={t('a11y.readableText.description')}
            checked={preferences.readableText}
            onChange={set('readableText')}
          />
          <Switch
            label={t('a11y.strongFocus')}
            description={t('a11y.strongFocus.description')}
            checked={preferences.strongFocus}
            onChange={set('strongFocus')}
          />
        </div>
      </Section>
      <Section title={t('a11y.keyboard')} padded>
        <ul className="grid gap-2 text-callout text-ink-secondary sm:grid-cols-2">
          {['skip', 'tab', 'escape', 'arrows'].map((key) => (
            <li key={key} className="flex gap-3">
              <kbd className="inline-flex h-6 min-w-14 shrink-0 items-center justify-center rounded border border-hairline-strong bg-surface-muted px-1.5 font-mono text-caption text-ink">
                {t(`a11y.keyboard.${key}.key`)}
              </kbd>
              <span>{t(`a11y.keyboard.${key}`)}</span>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}
