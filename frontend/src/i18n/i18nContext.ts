import { createContext } from 'react';
import { DEFAULT_LANGUAGE, translator, type Language } from './messages.ts';

export interface I18nContextValue {
  /** the interface language */
  language: Language;
  /** changes it, for this browser */
  setLanguage: (language: Language) => void;
  /** the text of a key */
  t: (key: string, values?: Record<string, string | number>) => string;
}

/**
 * English until a provider says otherwise, so a component rendered on its own (in a test) reads
 * the same texts as in the application.
 */
export const I18nContext = createContext<I18nContextValue>({
  language: DEFAULT_LANGUAGE,
  setLanguage: () => {},
  t: translator(DEFAULT_LANGUAGE),
});
