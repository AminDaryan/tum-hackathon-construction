import { useSyncExternalStore } from 'react';

/**
 * The reader's colour scheme: 'system' (the default) follows the operating system, 'light' and
 * 'dark' fix it. The choice is kept in this browser; the scheme in use is written to
 * <html data-color-scheme> (index.html does the same before the first paint) and announced with
 * a `twb:colorscheme` event for code that draws outside CSS, such as the 3D viewer. The tab icon
 * follows it too, so it shows the mark in the same colours as the app.
 */
export type ColorSchemePreference = 'system' | 'light' | 'dark';

const COLOR_SCHEME_PREFERENCES: readonly ColorSchemePreference[] = Object.freeze(['system', 'light', 'dark']);

const STORAGE_KEY = 'twb.colorScheme';
const DARK_QUERY = '(prefers-color-scheme: dark)';
/** The tab icon in each scheme: the mark in the colours of the logo tokens in index.css. */
const TAB_ICONS = Object.freeze({ light: '/favicon.svg', dark: '/favicon-dark.svg' });
const listeners = new Set<() => void>();

function systemDark() {
  return typeof window.matchMedia === 'function' && window.matchMedia(DARK_QUERY).matches;
}

function getColorSchemePreference(): ColorSchemePreference {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return COLOR_SCHEME_PREFERENCES.includes(stored as ColorSchemePreference) ? (stored as ColorSchemePreference) : 'system';
  } catch {
    return 'system';
  }
}

/** The scheme in use for a preference: 'light' or 'dark'. */
function resolveColorScheme(preference = getColorSchemePreference()): 'light' | 'dark' {
  if (preference === 'system') return systemDark() ? 'dark' : 'light';
  return preference;
}

function apply() {
  const scheme = resolveColorScheme();
  const root = document.documentElement;
  if (root.dataset.colorScheme !== scheme) {
    root.dataset.colorScheme = scheme;
    window.dispatchEvent(new CustomEvent('twb:colorscheme', { detail: scheme }));
  }
  document.querySelector('link[rel="icon"]')?.setAttribute('href', TAB_ICONS[scheme]);
  listeners.forEach((listener) => listener());
}

export function setColorSchemePreference(preference: ColorSchemePreference) {
  try {
    if (preference === 'system') window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, preference);
  } catch {
    // Storage may be unavailable (private mode); the choice then lasts for this page.
  }
  current = preference;
  apply();
}

let current = getColorSchemePreference();

/** Applies the saved choice and follows the system setting while the choice is 'system'. */
export function startColorScheme() {
  current = getColorSchemePreference();
  apply();
  if (typeof window.matchMedia !== 'function') return () => {};
  const media = window.matchMedia(DARK_QUERY);
  const onChange = () => {
    if (current === 'system') apply();
  };
  media.addEventListener('change', onChange);
  return () => media.removeEventListener('change', onChange);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The reader's preference ('system', 'light' or 'dark'), re-rendering when it changes. */
export function useColorSchemePreference() {
  return useSyncExternalStore(subscribe, () => current, (): ColorSchemePreference => 'system');
}
