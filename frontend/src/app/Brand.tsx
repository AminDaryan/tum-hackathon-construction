import { useI18n } from '../i18n/useI18n.ts';

/**
 * The mark and the name "Desvio", at the leading edge of the top bar and of the navigation that
 * opens over it. Below 640 px the name is kept for screen readers only.
 */
export function Brand() {
  const { t } = useI18n();
  return (
    <span className="flex shrink-0 items-center gap-2.5">
      {/* Inline, in the logo tokens, so the mark follows the app's own colour scheme in the colours of the tab icon. */}
      <svg aria-hidden="true" viewBox="0 0 48 48" className="size-7 shrink-0">
        <path className="fill-logo" d="M8 0H21A24 24 0 0 1 43.04 14.5H28.96L14.96 28.5H3V5A5 5 0 0 1 8 0Z" />
        <path className="fill-logo-secondary" d="M3 33.5H17.04L31.04 19.5H44.574A24 24 0 0 1 21 48H8A5 5 0 0 1 3 43Z" />
      </svg>
      <span className="text-callout font-semibold text-ink max-sm:sr-only">{t('app.name')}</span>
    </span>
  );
}
