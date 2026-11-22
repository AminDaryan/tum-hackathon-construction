import { Monitor, Moon, Sun, type LucideIcon } from 'lucide-react';
import { SegmentedControl } from '../components/SegmentedControl.tsx';
import { useI18n } from '../i18n/useI18n.ts';
import { setColorSchemePreference, useColorSchemePreference, type ColorSchemePreference } from './colorScheme.ts';

/** The three choices, in order, with their icon; `labelKey` names them in the interface language. */
const COLOR_SCHEME_OPTIONS = Object.freeze<{ id: ColorSchemePreference; labelKey: string; icon: LucideIcon }[]>([
  { id: 'system', labelKey: 'appearance.system', icon: Monitor },
  { id: 'light', labelKey: 'appearance.light', icon: Sun },
  { id: 'dark', labelKey: 'appearance.dark', icon: Moon },
]);

/** System, Light or Dark as a segmented control, in Settings, General. */
export function ColorSchemeSwitch() {
  const { t } = useI18n();
  const preference = useColorSchemePreference();
  return (
    <SegmentedControl
      label={t('appearance.label')}
      value={preference}
      options={COLOR_SCHEME_OPTIONS.map(({ id, labelKey, icon }) => ({ value: id, label: t(labelKey), icon }))}
      onChange={setColorSchemePreference}
    />
  );
}
