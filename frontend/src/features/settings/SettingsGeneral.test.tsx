import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { mockFetch } from '../../test/fetchMock.ts';
import { detectorCatalogue, health } from '../../test/fixtures.ts';
import { renderApp } from '../../test/render.tsx';

describe('Settings', () => {
  it('opens over the projects with only General, Accessibility and System, on General', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    const { location } = renderApp('/settings');
    const dialog = await screen.findByRole('dialog', { name: 'Settings' });
    expect(within(dialog).getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['General', 'Accessibility', 'System']);
    expect(within(dialog).getByRole('tab', { name: 'General', selected: true })).toBeInTheDocument();
    await waitFor(() => expect(location()).toBe('/projects'));
    expect(await screen.findByRole('heading', { level: 1, name: 'Projects', hidden: true })).toBeInTheDocument();
  });

  it('switches the language on General', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    const { user } = renderApp('/settings');
    const dialog = await screen.findByRole('dialog', { name: 'Settings' });
    expect(within(dialog).getByText('The interface is in English.')).toBeInTheDocument();
    await user.click(within(within(dialog).getByRole('group', { name: 'Language' })).getByRole('button', { name: 'Deutsch' }));

    const german = await screen.findByRole('dialog', { name: 'Einstellungen' });
    expect(within(german).getByRole('tab', { name: 'Allgemein', selected: true })).toBeInTheDocument();
    expect(within(german).getByText('Die Oberfläche ist auf Deutsch.')).toBeInTheDocument();
  });

  it('switches the colour scheme on General', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    const { user } = renderApp('/settings');
    const choice = await screen.findByRole('radiogroup', { name: 'Colour scheme' });
    expect(within(choice).getByRole('radio', { name: 'System' })).toBeChecked();
    await user.click(within(choice).getByRole('radio', { name: 'Light' }));
    expect(document.documentElement.dataset.colorScheme).toBe('light');
    expect(within(choice).getByRole('radio', { name: 'Light' })).toBeChecked();
    await user.click(within(choice).getByRole('radio', { name: 'System' }));
  });

  it('shows on System the status, version, checks and profiles of the backend, and nothing about server setup', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }, 
      { path: '/api/v1/health', respond: health },
      { path: '/api/v1/detectors', respond: detectorCatalogue },
    ]);
    renderApp('/settings?tab=system');
    const dialog = await screen.findByRole('dialog', { name: 'Settings' });
    const backend = await within(dialog).findByRole('region', { name: 'Backend' });
    expect(within(backend).getAllByRole('term').map((term) => term.textContent)).toEqual([
      'Status',
      'Version',
      'Detectors registered',
      'Profiles',
      'Default profile',
    ]);
    for (const gone of ['Access', 'Unavailable detectors', 'AI planner', 'Sign-in', 'API base URL']) {
      expect(within(dialog).queryByText(gone)).not.toBeInTheDocument();
    }
    expect(within(dialog).queryByRole('button', { name: 'Check again' })).not.toBeInTheDocument();
  });
});

describe('Settings, the old Users tab', () => {
  it('goes to the Users page', async () => {
    mockFetch([{ path: '/api/v1/users', respond: [] }]);
    const { location } = renderApp('/settings?tab=users');
    expect(await screen.findByRole('heading', { level: 1, name: 'Users' })).toBeInTheDocument();
    expect(location()).toBe('/users');
  });
});
