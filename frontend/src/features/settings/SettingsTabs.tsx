import type { ComponentType } from 'react';
import { Tabs } from '../../components/Tabs.tsx';
import { useI18n } from '../../i18n/useI18n.ts';
import { AccessibilityPanel } from './AccessibilityPanel.tsx';
import { GeneralPanel } from './GeneralPanel.tsx';
import { SystemPanel } from './SystemPanel.tsx';

const SETTINGS_TAB_IDS: readonly string[] = ['general', 'accessibility', 'system'];
export const DEFAULT_SETTINGS_TAB = 'general';

const PANELS: Readonly<Record<string, ComponentType>> = {
  general: GeneralPanel,
  accessibility: AccessibilityPanel,
  system: SystemPanel,
};

interface SettingsTabsProps {
  tab?: string | null;
  onSelect: (id: string) => void;
  className?: string;
  panelClassName?: string;
}

/**
 * The sections of Settings as tabs: the interface language and colour scheme (General), text
 * size, contrast, motion and reading aids (Accessibility), and the backend's status (System).
 * Shown over the current page (SettingsDialog).
 */
export function SettingsTabs({ tab, onSelect, className, panelClassName }: SettingsTabsProps) {
  const { t } = useI18n();
  const selected = tab && SETTINGS_TAB_IDS.includes(tab) ? tab : DEFAULT_SETTINGS_TAB;
  const Panel = PANELS[selected];
  return (
    <Tabs
      label={t('settings.sections')}
      tabs={SETTINGS_TAB_IDS.map((id) => ({ id, label: t(`settings.tab.${id}`) }))}
      selectedId={selected}
      onSelect={onSelect}
      className={className}
      panelClassName={panelClassName}
    >
      <Panel />
    </Tabs>
  );
}
