import { HIT_TARGET } from '../../components/hitTarget.ts';
import { useI18n } from '../../i18n/useI18n.ts';
import { LANGUAGES } from '../../i18n/messages.ts';
import { cx } from '../../utils/classNames.ts';

/** English or German (Settings, General): two toggle buttons, the current one pressed. */
export function LanguageSwitch() {
  const { language, setLanguage, t } = useI18n();
  return (
    <div
      role="group"
      aria-label={t('language.label')}
      className="inline-flex items-center gap-0.5 rounded-full border border-hairline bg-surface-muted"
    >
      {LANGUAGES.map((option) => {
        const pressed = option.id === language;
        return (
          <button
            key={option.id}
            type="button"
            lang={option.id}
            aria-pressed={pressed}
            title={t('language.switchTo', { language: option.label })}
            onClick={() => setLanguage(option.id)}
            className={cx(
              'inline-flex items-center justify-center rounded-full px-4 text-callout font-medium transition-colors',
              HIT_TARGET,
              pressed ? 'bg-surface text-ink shadow-popover' : 'text-ink-secondary hover:text-ink',
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
