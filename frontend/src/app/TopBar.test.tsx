import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ACCESS_TOKEN_STORAGE_KEY } from '../services/accessToken.ts';
import { LANGUAGE_STORAGE_KEY } from '../i18n/I18nProvider.tsx';
import { DEFAULT_ME, mockFetch } from '../test/fetchMock.ts';
import { openNavigation } from '../test/navigation.ts';
import { renderApp } from '../test/render.tsx';
import type { ReviewerSession } from '../services/apiTypes.ts';

const ANNA = Object.freeze({
  kind: 'user',
  name: 'Anna Schmidt',
  email: 'anna@example.test',
  role: 'reviewer',
  user_id: 'usr_1',
  auth_required: false,
  permissions: ['read', 'write'],
  account: null,
});
const VERA = Object.freeze({ ...ANNA, name: 'Vera', email: '', role: 'viewer', user_id: 'usr_2', permissions: ['read'] });

const topBar = () => within(screen.getByRole('banner', { name: 'Top bar' }));
/** The application renders once the health check answered. */
const started = () => screen.findByRole('banner', { name: 'Top bar' });

describe('top bar and user menu', () => {
  it('names the section, shows the name and role in the user menu and offers Profile, Settings, the reviewer and Log out', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    const { user, location } = renderApp('/projects');
    await started();

    expect(topBar().getByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument();
    // No subtitle under the title.
    expect(topBar().getByRole('heading', { level: 1 }).nextElementSibling).toBeNull();
    expect(topBar().queryByRole('group', { name: 'Language' })).not.toBeInTheDocument();
    const avatar = await topBar().findByRole('button', { name: 'Open the user menu of Local administrator' });
    expect(avatar).toHaveAttribute('aria-haspopup', 'menu');
    expect(topBar().queryByText('Administrator')).not.toBeInTheDocument();

    await user.click(avatar);
    const menu = screen.getByRole('menu', { name: 'User menu' });
    expect(within(menu).getByText('Local administrator')).toBeInTheDocument();
    expect(within(menu).getByText('Administrator')).toBeInTheDocument();
    const items = within(menu).getAllByRole('menuitem');
    expect(items.map((item) => item.textContent)).toEqual(['Profile', 'Settings', 'Choose reviewer…', 'Log out']);
    expect(items[0]).toHaveFocus();
    expect(items[3]).toHaveAttribute('aria-disabled', 'true'); // sign-in is off: nothing to log out of
    expect(within(menu).queryByText(/Sign-in is off/)).not.toBeInTheDocument();
    // The colour scheme is in Settings, not here.
    expect(within(menu).queryByRole('group', { name: 'Colour scheme' })).not.toBeInTheDocument();

    await user.keyboard('{ArrowDown}');
    expect(items[1]).toHaveFocus();
    await user.keyboard('{End}');
    expect(items[3]).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(items[0]).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(avatar).toHaveFocus();

    await user.click(avatar);
    // Profile opens over the page: the address and the page under it stay.
    await user.click(screen.getByRole('menuitem', { name: 'Profile' }));
    const profile = await screen.findByRole('dialog', { name: 'Profile' });
    expect(within(profile).queryByRole('tab')).not.toBeInTheDocument();
    expect(location()).toBe('/projects');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('joins and switches reviewers from the user menu, and shows their notifications in the top bar', async () => {
    let session: ReviewerSession = { reviewer: null, reviewers: [{ handle: 'larissa', name: 'Larissa' }] };
    const api = mockFetch([
      { path: '/api/v1/projects', respond: [] },
      { path: '/api/v1/collaboration/session', respond: () => session },
      {
        method: 'POST',
        path: '/api/v1/collaboration/session',
        respond: (call) => {
          const name = JSON.parse(call.body).name;
          const person = { handle: name.toLowerCase(), name };
          session = { reviewer: person, reviewers: [...session.reviewers.filter((other) => other.handle !== person.handle), person] };
          return session;
        },
      },
      { path: '/api/v1/collaboration/notifications', respond: { items: [], unread_count: 2 } },
    ]);
    const { user } = renderApp('/projects');
    await started();
    // No reviewer bar on the page; the bell waits for a reviewer.
    expect(screen.queryByRole('button', { name: 'Choose reviewer' })).not.toBeInTheDocument();
    expect(topBar().queryByRole('button', { name: /^Notifications/ })).not.toBeInTheDocument();

    await user.click(await topBar().findByRole('button', { name: /^Open the user menu/ }));
    await user.click(await screen.findByRole('menuitem', { name: 'Choose reviewer…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Choose reviewer' });
    await user.type(within(dialog).getByLabelText(/Your name/), 'Johan');
    await user.click(within(dialog).getByRole('button', { name: 'Join review' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(JSON.parse(api.callsTo('POST', '/api/v1/collaboration/session')[0].body)).toEqual({ name: 'Johan' });
    expect(await topBar().findByRole('button', { name: 'Notifications, 2 unread' })).toBeInTheDocument();
    expect(topBar().getByRole('button', { name: 'Open the user menu of Local administrator, Current reviewer: Johan' })).toHaveTextContent('Johan');

    await user.click(topBar().getByRole('button', { name: /^Open the user menu/ }));
    const reviewers = within(screen.getByRole('group', { name: 'Reviewer' })).getAllByRole('menuitemradio');
    expect(reviewers.map((item) => [item.textContent, item.getAttribute('aria-checked')])).toEqual([
      ['Johan', 'true'],
      ['Larissa', 'false'],
    ]);
    await user.click(reviewers[1]);
    expect(JSON.parse(api.callsTo('POST', '/api/v1/collaboration/session')[1].body)).toEqual({ name: 'Larissa' });
    const current = await topBar().findByRole('button', { name: 'Open the user menu of Local administrator, Current reviewer: Larissa' });
    expect(current).toHaveTextContent('Larissa');
    expect(current).not.toHaveTextContent('Johan');
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    await user.click(current);
    expect(screen.getByRole('menuitemradio', { name: 'Larissa' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('menuitemradio', { name: 'Johan' })).toHaveAttribute('aria-checked', 'false');
    expect(within(screen.getByRole('menu')).getByText('Administrator')).toBeInTheDocument();
    await user.keyboard('{Escape}');

    await user.click(topBar().getByRole('button', { name: 'Notifications, 2 unread' }));
    expect(screen.getByRole('region', { name: 'Notifications' })).toHaveTextContent('No mentions yet');
  });

  it('translates reviewer labels into German without translating a long reviewer name', async () => {
    const name = 'Alexandra_Maria_Mustermann';
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'de');
    mockFetch([
      { path: '/api/v1/projects', respond: [] },
      { path: '/api/v1/collaboration/session', respond: { reviewer: { handle: name.toLowerCase(), name }, reviewers: [] } },
      { path: '/api/v1/collaboration/notifications', respond: { items: [], unread_count: 0 } },
    ]);
    const { user } = renderApp('/projects');
    const trigger = await screen.findByRole('button', { name: new RegExp(`Aktueller Prüfer: ${name}$`) });
    expect(trigger).toHaveTextContent(`Prüfer${name}`);
    expect(trigger).toHaveAttribute('title', expect.stringContaining(name));
    await user.click(trigger);
    expect(within(screen.getByRole('group', { name: 'Prüfer' })).getByRole('menuitemradio', { name })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('menuitem', { name: 'Als jemand anderes teilnehmen…' })).toBeInTheDocument();
  });

  it('marks a viewer as read only', async () => {
    mockFetch([
      { path: '/api/v1/me', respond: VERA },
      { path: '/api/v1/projects', respond: [] },
    ]);
    const { user } = renderApp('/projects');
    await started();
    const avatar = await topBar().findByRole('button', { name: 'Open the user menu of Vera' });
    expect(topBar().getByText('Read only')).toBeInTheDocument();
    await user.click(avatar);
    expect(within(screen.getByRole('menu', { name: 'User menu' })).getByText('Viewer')).toBeInTheDocument();
  });

  it('logs a signed-in user out, back to the local administrator', async () => {
    mockFetch([
      { path: '/api/v1/me', respond: (call) => (call.headers.get('Authorization') === 'Bearer twb_anna' ? ANNA : DEFAULT_ME) },
      { path: '/api/v1/projects', respond: [] },
    ]);
    window.sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'twb_anna');
    const { user } = renderApp('/projects');
    await started();

    await user.click(await topBar().findByRole('button', { name: 'Open the user menu of Anna Schmidt' }));
    const logOut = screen.getByRole('menuitem', { name: 'Log out' });
    expect(logOut).not.toHaveAttribute('aria-disabled');
    await user.click(logOut);

    expect(await topBar().findByRole('button', { name: 'Open the user menu of Local administrator' })).toBeInTheDocument();
    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
    expect(screen.queryByRole('dialog', { name: 'Sign in to Desvio' })).not.toBeInTheDocument();
  });

  it('opens Settings from the user menu over the page, with no Settings in the navigation', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    const { user, location } = renderApp('/projects');
    await started();
    // The avatar shows the initials, with no arrow beside them.
    const avatar = await topBar().findByRole('button', { name: 'Open the user menu of Local administrator' });
    expect(avatar).toHaveTextContent(/^LA$/);
    const nav = await openNavigation(user);
    expect(nav.queryByRole('button', { name: 'Settings' })).not.toBeInTheDocument();
    expect(nav.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Primary' })).not.toBeInTheDocument());

    await user.click(avatar);
    const settings = screen.getByRole('menuitem', { name: 'Settings' });
    await user.click(settings);
    const dialog = await screen.findByRole('dialog', { name: 'Settings' });
    expect(within(dialog).getByRole('tab', { name: 'General', selected: true })).toBeInTheDocument();
    expect(within(dialog).queryByRole('tab', { name: 'Users' })).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole('tab', { name: 'Accessibility' }));
    expect(within(dialog).getByRole('tab', { name: 'Accessibility', selected: true })).toBeInTheDocument();
    // The page under it never changed: closing returns to it.
    expect(location()).toBe('/projects');
    await user.click(within(dialog).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument();
  });

  it('lists Users under Projects only for those who manage the accounts', async () => {
    mockFetch([
      { path: '/api/v1/projects', respond: [] },
      { path: '/api/v1/me', respond: VERA },
    ]);
    const { user } = renderApp('/projects');
    await started();
    await topBar().findByRole('button', { name: 'Open the user menu of Vera' });
    const nav = await openNavigation(user);
    expect(nav.getAllByRole('link').map((link) => link.textContent)).toEqual(['Projects']);
  });
});
