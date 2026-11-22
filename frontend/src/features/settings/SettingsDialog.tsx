import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { Dialog } from '../../components/Dialog.tsx';
import { useI18n } from '../../i18n/useI18n.ts';
import { MyProfilePanel } from './MyProfilePanel.tsx';
import { DEFAULT_SETTINGS_TAB, SettingsTabs } from './SettingsTabs.tsx';

interface Overlays {
  openSettings: (id?: string | null) => void;
  openProfile: () => void;
}

const OverlaysContext = createContext<Overlays | null>(null);

/**
 * Settings and the person's own profile over the page they are on, never as pages of their own:
 * opening either leaves the project, file or list behind it as it was, blurred and darkened, and
 * closing returns to it. `useOpenSettings()` opens Settings, optionally at a tab;
 * `useOpenProfile()` opens the profile.
 */
export function SettingsDialogProvider({ children }: { children?: ReactNode }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<string | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const openSettings = useCallback((id?: string | null) => setTab(id ?? DEFAULT_SETTINGS_TAB), []);
  const openProfile = useCallback(() => setProfileOpen(true), []);
  const value = useMemo(() => ({ openSettings, openProfile }), [openSettings, openProfile]);
  return (
    <OverlaysContext value={value}>
      {children}
      <Dialog open={tab !== null} onOpenChange={(isOpen) => !isOpen && setTab(null)} title={t('settings.title')} size="xl" backdrop="blur">
        <SettingsTabs tab={tab} onSelect={setTab} className="flex h-[70dvh] flex-col" panelClassName="min-h-0 flex-1 overflow-y-auto pt-4" />
      </Dialog>
      <Dialog open={profileOpen} onOpenChange={setProfileOpen} title={t('menu.profile')} size="xl" backdrop="blur">
        <div className="max-h-[70dvh] overflow-y-auto">
          <MyProfilePanel />
        </div>
      </Dialog>
    </OverlaysContext>
  );
}

/** Opens Settings over the current page: `open()` or `open('system')`. */
export function useOpenSettings() {
  const overlays = useContext(OverlaysContext);
  const navigate = useNavigate();
  return overlays?.openSettings ?? ((id?: string | null) => navigate(id ? `/settings?tab=${id}` : '/settings'));
}

/** Opens the person's own profile over the current page. */
export function useOpenProfile() {
  const overlays = useContext(OverlaysContext);
  const navigate = useNavigate();
  return overlays?.openProfile ?? (() => navigate('/settings?tab=profile'));
}

/**
 * An old or typed link to Settings (/settings?tab=): the projects, with Settings (or, for
 * `tab=profile`, the profile) open over them. The user accounts moved to /users.
 */
export function SettingsLink() {
  const [searchParams] = useSearchParams();
  const requested = searchParams.get('tab');
  const overlays = useContext(OverlaysContext);
  useEffect(() => {
    if (!overlays || requested === 'users') return;
    if (requested === 'profile') overlays.openProfile();
    else overlays.openSettings(requested);
  }, [overlays, requested]);
  return <Navigate to={requested === 'users' ? '/users' : '/projects'} replace />;
}
