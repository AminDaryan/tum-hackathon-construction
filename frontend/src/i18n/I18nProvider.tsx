import { useCallback, useEffect, useMemo, useState } from 'react';
import { I18nProvider as AriaI18nProvider } from 'react-aria-components';
import { readStorage, writeStorage } from '../utils/safeStorage.ts';
import { I18nContext } from './i18nContext.ts';
import { applyLanguage, DEFAULT_LANGUAGE, intlLocale, isLanguage, translator, type Language } from './messages.ts';
import type { ReactNode } from 'react';

export const LANGUAGE_STORAGE_KEY = 'twb.language';

/**
 * The stored choice, else the first English or German entry in the browser's languages, else
 * English.
 */
export function initialLanguage(): Language {
  const stored = readStorage(LANGUAGE_STORAGE_KEY);
  if (isLanguage(stored)) return stored;
  const preferred = typeof navigator === 'undefined' ? [] : navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const tag of preferred) {
    const language = String(tag ?? '').toLowerCase().split('-')[0];
    if (isLanguage(language)) return language;
  }
  return DEFAULT_LANGUAGE;
}

interface I18nProviderProps {
  children?: ReactNode;
}

/**
 * The interface language: this browser's choice (Settings, General), else the browser's
 * preferred languages, else English. The choice is kept in localStorage and set as
 * `<html lang>`, so screen readers pronounce the texts in the right language. It is also applied
 * to the module-level `t` and the formatters (numbers and dates follow it) before the next
 * render, and given to React Aria's components.
 */
export function I18nProvider({ children }: I18nProviderProps) {
  const [language, setLanguageState] = useState(() => {
    const initial = initialLanguage();
    applyLanguage(initial);
    return initial;
  });

  useEffect(() => {
    applyLanguage(language);
    document.documentElement.lang = language;
  }, [language]);

  const setLanguage = useCallback((next: string) => {
    if (!isLanguage(next)) return;
    applyLanguage(next);
    writeStorage(LANGUAGE_STORAGE_KEY, next);
    setLanguageState(next);
  }, []);

  const value = useMemo(() => ({ language, setLanguage, t: translator(language) }), [language, setLanguage]);
  return (
    <I18nContext.Provider value={value}>
      <AriaI18nProvider locale={intlLocale(language)}>{children}</AriaI18nProvider>
    </I18nContext.Provider>
  );
}
