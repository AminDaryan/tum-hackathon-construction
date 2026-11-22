import { useLayoutEffect } from 'react';

const APP_NAME = 'Desvio Risk Intelligence';

/**
 * Sets the browser tab title to "<title> — Desvio Risk Intelligence". It is set with the page's
 * commit (a layout effect), so the tab never names the page before.
 *
 * @param title page title; empty means the application name only
 */
export function useDocumentTitle(title: string | null | undefined): void {
  useLayoutEffect(() => {
    document.title = title ? `${title} — ${APP_NAME}` : APP_NAME;
  }, [title]);
}
