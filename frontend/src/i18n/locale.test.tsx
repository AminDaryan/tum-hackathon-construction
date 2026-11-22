import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../test/fetchMock.ts';
import { renderApp } from '../test/render.tsx';
import { formatCount, formatDateTime, formatDecimal } from '../utils/format.ts';
import { initialLanguage, LANGUAGE_STORAGE_KEY } from './I18nProvider.tsx';
import { applyLanguage, t } from './messages.ts';

afterEach(() => {
  applyLanguage('en');
  vi.restoreAllMocks();
});

describe('UI language', () => {
  it('starts in the stored choice, else the browser language, else English', () => {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['fr-FR', 'de-AT', 'en-GB']);
    expect(initialLanguage()).toBe('de');
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['fr-FR', 'it']);
    expect(initialLanguage()).toBe('en');
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'de');
    expect(initialLanguage()).toBe('de');
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'xx');
    expect(initialLanguage()).toBe('en');
  });

  it('switches page content to German and keeps the choice for the next visit', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    const { user, unmount } = renderApp('/settings');
    const choice = await screen.findByRole('group', { name: 'Language' });
    await user.click(within(choice).getByRole('button', { name: 'Deutsch' }));

    expect(await screen.findByRole('tab', { name: 'Allgemein', selected: true })).toBeInTheDocument();
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('de');
    expect(document.documentElement.lang).toBe('de');
    unmount();

    // A page translated with the module-level t, on a fresh start with the stored choice.
    mockFetch([]);
    renderApp('/no-such-page');
    expect(await screen.findByRole('link', { name: 'Zu den Projekten' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Zum Hauptinhalt springen' })).toBeInTheDocument();
  });

  it('formats numbers and dates in the language and keeps every digit of a decimal string', () => {
    expect(formatDecimal('12345678901234567890.125')).toBe('12,345,678,901,234,567,890.125');
    expect(formatDecimal('-0.90')).toBe('-0.90');
    applyLanguage('de');
    expect(formatDecimal('12345678901234567890.125')).toBe('12.345.678.901.234.567.890,125');
    expect(formatDecimal('1250.50', { signed: true })).toBe('+1.250,50');
    expect(formatDecimal('-0.90')).toBe('-0,90');
    expect(formatCount(12345)).toBe('12.345');
    expect(formatDateTime('2026-11-17T20:05:00Z')).toMatch(/^\d{2}\.11\.2026, \d{2}:05$/);
    expect(t('Showing {count} of {total} risks.', { count: 2, total: 5 })).not.toContain('Showing');
    expect(t('Text from an uploaded bill')).toBe('Text from an uploaded bill');
  });

  it('shows the projects table in German, with German dates and the count in the singular', async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'de');
    mockFetch([
      {
        path: '/api/v1/projects',
        respond: [
          {
            project_id: 'prj_1',
            name: 'Riverside',
            description: 'Bridge works',
            created_at: '2026-11-21T10:00:00Z',
            status: 'in_progress',
            assignees: [],
            decision_cutoff: null,
            files: [],
            demo_key: null,
            preparation: 'ready',
            preparation_error: null,
            validation: null,
          },
        ],
      },
    ]);
    renderApp('/projects');
    const table = await screen.findByRole('grid');
    expect(within(table).getAllByRole('columnheader').map((header) => header.textContent)).toEqual([
      'Name',
      'Beschreibung',
      'Zuständig',
      'Dateien',
      'Erstellt',
      'Status',
    ]);
    expect(await within(table).findByText('21.11.2026')).toBeInTheDocument();
    expect(within(table).getByRole('button', { name: 'In Bearbeitung Status von Riverside' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Projekt anlegen' })).toBeInTheDocument();
    expect(screen.getByText('1–1 von 1 Projekt')).toBeInTheDocument();
  });
});
