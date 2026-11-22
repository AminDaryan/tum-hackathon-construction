import { ColorSchemeSwitch } from '../../app/ColorSchemeSwitch.tsx';
import { Section } from '../../components/Section.tsx';
import { useI18n } from '../../i18n/useI18n.ts';
import { LanguageSwitch } from './LanguageSwitch.tsx';

/** Settings, General: the interface language and the colour scheme, both for this browser. */
export function GeneralPanel() {
  const { t } = useI18n();
  return (
    <>
      <Section title={t('general.language.title')} description={t('general.language.description')} padded>
        <div className="flex flex-wrap items-center gap-4">
          <LanguageSwitch />
          <p role="status" className="text-callout text-ink-secondary">
            {t('general.language.current')}
          </p>
        </div>
      </Section>
      <Section title={t('appearance.title')} description={t('appearance.description')} padded>
        <ColorSchemeSwitch />
      </Section>
    </>
  );
}
