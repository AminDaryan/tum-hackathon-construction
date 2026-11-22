import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { errorResponse, mockFetch, pendingUntilAborted } from '../test/fetchMock.ts';
import { findProjectNav, openNavigation } from '../test/navigation.ts';
import { renderApp } from '../test/render.tsx';
import type { Project, UserAccount } from '../services/apiTypes.ts';

type Queries = Awaited<ReturnType<typeof openNavigation>>;
const linkTexts = (nav: Queries) => nav.getAllByRole('link').map((link) => link.textContent);

/** Project `n`, created on day `n` of November. */
function project(n: number): Project {
  return {
    project_id: `prj_${n}`,
    name: `Project ${n}`,
    description: '',
    created_at: `2026-11-${String(n).padStart(2, '0')}T10:00:00Z`,
    status: 'in_progress',
    assignees: [],
    decision_cutoff: null,
    files: [],
    demo_key: null,
    preparation: 'ready',
    preparation_error: null,
    validation: null,
  };
}

function account(n: number): UserAccount {
  return {
    user_id: `usr_${n}`,
    name: `User ${n}`,
    first_name: `User ${n}`,
    last_name: '',
    email: '',
    job_title: '',
    phone: '',
    role: 'reviewer',
    active: true,
    created_at: '2026-11-20T09:00:00Z',
    token_hint: null,
    token_issued_at: null,
  };
}

// Seven of each, the projects in the order the server sends them (oldest first).
const PROJECTS = [1, 2, 3, 4, 5, 6, 7].map(project);
const USERS = [1, 2, 3, 4, 5, 6, 7].map(account);

describe('navigation', () => {
  it('opens over the page from the menu button, and closes with it, with Escape or by going somewhere', async () => {
    mockFetch([
      { path: '/api/v1/projects', respond: PROJECTS },
      { path: '/api/v1/users', respond: USERS },
    ]);
    const { user, location } = renderApp('/projects');
    await screen.findByRole('heading', { level: 1, name: 'Projects' });
    const menuButton = screen.getByRole('button', { name: 'Open the navigation' });
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('navigation', { name: 'Primary' })).not.toBeInTheDocument();
    // Beside the mark the top bar says "Desvio", nothing else.
    expect(within(screen.getByRole('banner', { name: 'Top bar' })).getByText('Desvio')).toBeInTheDocument();
    expect(screen.queryByText(/Risk Intelligence/)).not.toBeInTheDocument();

    await openNavigation(user);
    expect(screen.getByRole('dialog', { name: 'Primary' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close the navigation' }));
    await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Primary' })).not.toBeInTheDocument());

    await openNavigation(user);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Primary' })).not.toBeInTheDocument());

    const nav = await openNavigation(user);
    await user.click(await nav.findByRole('link', { name: 'Users' }));
    await waitFor(() => expect(location()).toBe('/users'));
    await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Primary' })).not.toBeInTheDocument());
    expect(await screen.findByRole('heading', { level: 1, name: 'Users' })).toBeInTheDocument();
  });

  it('lists the five newest projects and the first five users, each with More …', async () => {
    mockFetch([
      { path: '/api/v1/projects', respond: PROJECTS },
      { path: '/api/v1/users', respond: USERS },
    ]);
    const { user } = renderApp('/projects');
    await screen.findByRole('heading', { level: 1, name: 'Projects' });
    const nav = await openNavigation(user);
    await nav.findByRole('link', { name: 'User 1' });
    expect(linkTexts(nav)).toEqual([
      'Projects',
      'Project 7',
      'Project 6',
      'Project 5',
      'Project 4',
      'Project 3',
      'More projects',
      'Users',
      'User 1',
      'User 2',
      'User 3',
      'User 4',
      'User 5',
      'More users',
    ]);
    expect(nav.getByRole('link', { current: 'page' })).toHaveAccessibleName('Projects');
    expect(nav.getByRole('link', { name: 'Project 7' })).toHaveAttribute('href', '/projects/prj_7');
    expect(nav.getByRole('link', { name: 'More projects' })).toHaveAttribute('href', '/projects');
    expect(nav.getByRole('link', { name: 'More projects' })).not.toHaveAttribute('aria-current');
    expect(nav.getByRole('link', { name: 'User 1' })).toHaveAttribute('href', '/users/usr_1');
    expect(nav.getByRole('link', { name: 'More users' })).toHaveAttribute('href', '/users');
    // Each section's + sits in the row of its heading.
    expect(nav.getAllByRole('button').map((button) => button.getAttribute('aria-label'))).toEqual(['Create project', 'Add user']);
  });

  it('adds the open project after the newest ones and the open user after the first ones, each marked as the current page', async () => {
    mockFetch([
      { path: '/api/v1/projects', respond: PROJECTS },
      { path: '/api/v1/projects/prj_1', respond: pendingUntilAborted },
      { path: '/api/v1/projects/prj_1/reports', respond: pendingUntilAborted },
      { path: '/api/v1/users', respond: USERS },
    ]);
    const { user } = renderApp('/projects/prj_1/reports');
    // The project's own pages are in the bar under the top bar, not in the navigation.
    expect((await findProjectNav()).getByRole('link', { current: 'page' })).toHaveAccessibleName('Reports');
    let nav = await openNavigation(user);
    await nav.findByRole('link', { name: 'Project 1' });
    await nav.findByRole('link', { name: 'User 1' });
    expect(linkTexts(nav).slice(0, 8)).toEqual(['Projects', 'Project 7', 'Project 6', 'Project 5', 'Project 4', 'Project 3', 'Project 1', 'More projects']);
    expect(nav.getByRole('link', { current: 'page' })).toHaveAccessibleName('Project 1');

    await user.click(nav.getByRole('link', { name: 'More users' }));
    const table = await screen.findByRole('grid', { name: /^User accounts/ });
    await user.click(await within(table).findByText('User 7'));
    await screen.findByRole('heading', { level: 1, name: 'User 7' });
    nav = await openNavigation(user);
    expect(nav.getByRole('link', { current: 'page' })).toHaveAccessibleName('User 7');
    expect(linkTexts(nav).slice(-3)).toEqual(['User 5', 'User 7', 'More users']);
  });

  it('creates a project from the + beside Projects', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    const { user, location } = renderApp('/projects');
    await screen.findByRole('heading', { level: 1, name: 'Projects' });
    const nav = await openNavigation(user);
    await user.click(nav.getByRole('button', { name: 'Create project' }));
    expect(location()).toBe('/projects/new');
    expect(await screen.findByRole('heading', { level: 1, name: 'Create project' })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Primary' })).not.toBeInTheDocument());
  });

  it('adds a user from the + beside Users, and lists the new account', async () => {
    const created = account(8);
    let accounts = [account(1)];
    const api = mockFetch([
      { path: '/api/v1/users', respond: () => accounts },
      {
        method: 'POST',
        path: '/api/v1/users',
        respond: () => {
          accounts = [...accounts, created];
          return { user: created, token: 'twb_secret' };
        },
      },
    ]);
    const { user, location } = renderApp('/projects');
    await screen.findByRole('heading', { level: 1, name: 'Projects' });
    let nav = await openNavigation(user);
    await user.click(await nav.findByRole('button', { name: 'Add user' }));
    expect(location()).toBe('/users?add=1');
    const form = await screen.findByRole('form', { name: 'New user' });
    await user.type(within(form).getByLabelText('First name'), 'User 8');
    await user.click(within(form).getByRole('button', { name: 'Create user' }));

    expect(await screen.findByRole('region', { name: 'Access token for User 8' })).toBeInTheDocument();
    await waitFor(() => expect(location()).toBe('/users'));
    nav = await openNavigation(user);
    expect(await nav.findByRole('link', { name: 'User 8' })).toHaveAttribute('href', '/users/usr_8');
    expect(api.callsTo('POST', '/api/v1/users')).toHaveLength(1);
  });

  it('keeps Users in the navigation when the session cannot say who is signed in', async () => {
    mockFetch([
      { path: '/api/v1/me', respond: errorResponse(404, 'not_found', 'Not found') },
      { path: '/api/v1/projects', respond: PROJECTS },
      { path: '/api/v1/users', respond: USERS },
    ]);
    const { user } = renderApp('/projects');
    await screen.findByRole('heading', { level: 1, name: 'Projects' });
    const nav = await openNavigation(user);
    expect(await nav.findByRole('link', { name: 'Users' })).toHaveAttribute('href', '/users');
    expect(await nav.findByRole('link', { name: 'User 1' })).toBeInTheDocument();
  });

  it('reads no list while the application waits for the server', async () => {
    const api = mockFetch([{ path: '/api/v1/health', respond: pendingUntilAborted }]);
    renderApp('/projects/prj_1');
    expect(await screen.findByText('Connecting to the server…')).toBeInTheDocument();
    await waitFor(() => expect(api.callsTo('GET', '/api/v1/health')).toHaveLength(1));
    expect(api.callsTo('GET', '/api/v1/projects')).toHaveLength(0);
    expect(api.callsTo('GET', '/api/v1/users')).toHaveLength(0);
  });
});
