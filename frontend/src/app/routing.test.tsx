import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ACTIVE_DOCUMENT_STORAGE_KEY } from '../stores/activeDocumentStorage.ts';
import { errorResponse, mockFetch, pendingUntilAborted } from '../test/fetchMock.ts';
import { findProjectNav, openNavigation } from '../test/navigation.ts';
import { renderApp } from '../test/render.tsx';
import { projectWorkspaceRoutes, WORKSPACE_PROJECT } from '../test/workspaceRoutes.ts';

describe('routing', () => {
  it('redirects / to Projects, with Projects and Users in the navigation', async () => {
    const api = mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    const { user, location } = renderApp('/');

    await waitFor(() => expect(location()).toBe('/projects'));
    expect(screen.getByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument();
    expect(within(screen.getByRole('banner', { name: 'Top bar' })).getByText('Desvio')).toBeInTheDocument();
    const nav = await openNavigation(user);
    expect(nav.getAllByRole('link').map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Projects', '/projects'],
      ['Users', '/users'],
    ]);
    expect(nav.getAllByRole('button').map((button) => button.getAttribute('aria-label') ?? button.textContent)).toEqual([
      'Create project',
      'Add user',
    ]);
    expect(nav.getByRole('link', { name: 'Projects' })).toHaveAttribute('aria-current', 'page');
    // The top bar names the page before the projects table has asked for its rows; the
    // navigation lists the projects and users.
    await waitFor(() =>
      expect([...new Set(api.calls.map((call) => call.path))].sort()).toEqual([
        '/api/v1/collaboration/session',
        '/api/v1/health',
        '/api/v1/me',
        '/api/v1/projects',
        '/api/v1/users',
      ]),
    );
  });

  it.each([
    ['/workspace', '/projects'],
    ['/history', '/projects'],
    ['/coordination', '/projects'],
  ])('sends %s without an open file to %s, where the navigation marks Projects', async (from, to) => {
    mockFetch([{ path: '/api/v1/projects', respond: [WORKSPACE_PROJECT] }]);
    const { user, location } = renderApp(from);
    await waitFor(() => expect(location()).toBe(to));
    await screen.findByRole('heading', { level: 1, name: 'Projects' });
    const nav = await openNavigation(user);
    expect(nav.getByRole('link', { current: 'page' })).toHaveAccessibleName('Projects');
  });

  it('sends /workspace?project=prj_1 without an open file to the project\'s Workspace, which the project bar marks', async () => {
    mockFetch([
      { path: '/api/v1/projects', respond: [WORKSPACE_PROJECT] },
      { path: '/api/v1/projects/prj_1', respond: pendingUntilAborted },
    ]);
    const { location } = renderApp('/workspace?project=prj_1');
    await waitFor(() => expect(location()).toBe('/projects/prj_1/workspace'));
    expect((await findProjectNav()).getByRole('link', { current: 'page' })).toHaveAccessibleName('Workspace');
  });

  it('opens a remembered or linked file of /workspace in the Workspace of its project, with the project\'s pages in the bar under the top bar', async () => {
    mockFetch(projectWorkspaceRoutes());
    const { user, location } = renderApp('/workspace?document=doc_1&tab=risks');
    await waitFor(() => expect(location()).toBe('/projects/prj_1/workspace?document=doc_1&tab=risks'));
    const bar = await findProjectNav();
    expect(bar.getAllByRole('link').map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Overview', '/projects/prj_1'],
      ['Workspace', '/projects/prj_1/workspace'],
      ['Follow-ups', '/projects/prj_1/follow-ups'],
      ['Reports', '/projects/prj_1/reports'],
    ]);
    expect(bar.getByRole('link', { current: 'page' })).toHaveAccessibleName('Workspace');
    expect(await screen.findByRole('heading', { level: 1, name: 'tender.xlsx' })).toBeInTheDocument();
    // The top bar names the project; the bar under it starts with Overview, without the name.
    expect(await within(screen.getByRole('banner')).findByRole('link', { name: 'Riverside' })).toBeInTheDocument();
    const projectBar = screen.getByRole('navigation', { name: 'Project' }).parentElement as HTMLElement;
    expect(projectBar).not.toHaveTextContent('Riverside');
    expect(projectBar.textContent).toMatch(/^Overview/);
    const nav = await openNavigation(user);
    expect(await nav.findByRole('link', { current: 'page' })).toHaveAccessibleName('Riverside');
    expect(nav.getAllByRole('link').map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Projects', '/projects'],
      ['Riverside', '/projects/prj_1'],
      ['Users', '/users'],
    ]);
  });

  it('shows the project bar only on the pages of a project, and moves between them from it', async () => {
    mockFetch(projectWorkspaceRoutes());
    const { user, location } = renderApp('/projects');
    await screen.findByRole('heading', { level: 1, name: 'Projects' });
    expect(screen.queryByRole('navigation', { name: 'Project' })).not.toBeInTheDocument();

    await user.click(await screen.findByRole('row', { name: /Riverside/ }));
    await waitFor(() => expect(location()).toBe('/projects/prj_1'));
    const bar = await findProjectNav();
    expect(bar.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
    await user.click(bar.getByRole('link', { name: 'Follow-ups' }));
    expect(location()).toBe('/projects/prj_1/follow-ups');
    expect(await screen.findByRole('heading', { level: 1, name: 'Follow-ups' })).toBeInTheDocument();
    expect(bar.getByRole('link', { current: 'page' })).toHaveAccessibleName('Follow-ups');

    const nav = await openNavigation(user);
    await user.click(nav.getByRole('link', { name: 'Projects' }));
    await screen.findByRole('heading', { level: 1, name: 'Projects' });
    expect(screen.queryByRole('navigation', { name: 'Project' })).not.toBeInTheDocument();
  });

  it('fades a new page in, but not a change of its query string', async () => {
    mockFetch(projectWorkspaceRoutes());
    const animate = vi.fn(() => ({ finished: Promise.resolve() }));
    Object.defineProperty(HTMLElement.prototype, 'animate', { configurable: true, value: animate });
    try {
      const { user, location } = renderApp('/projects');
      await screen.findByRole('heading', { level: 1, name: 'Projects' });
      expect(animate).not.toHaveBeenCalled();

      await user.click(await (await openNavigation(user)).findByRole('link', { name: 'Users' }));
      await screen.findByRole('heading', { level: 1, name: 'Users' });
      expect(animate).toHaveBeenCalledTimes(1);
      expect(animate).toHaveBeenCalledWith([{ opacity: 0 }, { opacity: 1 }], expect.objectContaining({ duration: 150 }));
      // The page inside the main area, not the frame around it.
      expect(animate.mock.contexts[0]).toBe(screen.getByRole('main').firstElementChild);

      await user.click(within(screen.getByRole('main')).getByRole('button', { name: 'Add user' }));
      await waitFor(() => expect(location()).toBe('/users?add=1'));
      expect(animate).toHaveBeenCalledTimes(1);
    } finally {
      delete (HTMLElement.prototype as Partial<Pick<HTMLElement, 'animate'>>).animate;
    }
  });

  it('shows no reviewer bar on /projects', async () => {
    mockFetch([{ method: 'GET', path: '/api/v1/projects', respond: [] }]);
    renderApp('/projects');
    expect(await screen.findByText('No projects yet')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Choose reviewer' })).not.toBeInTheDocument();
    expect(screen.queryByText('Collaboration offline. Retrying…')).not.toBeInTheDocument();
  });

  it('shows the not-found page for an unknown address', async () => {
    mockFetch([]);
    const { location } = renderApp('/no/such/page');
    expect(await screen.findByRole('heading', { level: 2, name: 'There is nothing at this address' })).toBeInTheDocument();
    expect(screen.getByText('/no/such/page', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to projects' })).toHaveAttribute('href', '/projects');
    expect(location()).toBe('/no/such/page');
  });

  it('names Projects, not a missing page, while / waits for the server', async () => {
    mockFetch([{ path: '/api/v1/health', respond: pendingUntilAborted }]);
    renderApp('/');
    expect(await screen.findByText('Connecting to the server…')).toBeInTheDocument();
    expect(screen.getByText('Projects', { selector: 'p' })).toBeInTheDocument();
    expect(screen.queryByText('Page not found')).not.toBeInTheDocument();
  });

  it('names no missing page while an old address finds its new place', async () => {
    mockFetch([
      { path: '/api/v1/projects', respond: pendingUntilAborted },
      { path: '/api/v1/documents/doc_1', respond: pendingUntilAborted },
    ]);
    const { location } = renderApp('/workspace', { activeDocumentId: 'doc_1' });
    expect(await screen.findByText('Opening the file…')).toBeInTheDocument();
    expect(location()).toBe('/workspace');
    expect(screen.queryByText('Page not found')).not.toBeInTheDocument();
  });

  it.each(['/projects/prj_missing', '/projects/prj_missing/follow-ups', '/projects/prj_missing/edit'])(
    'shows the not-found page, without the project bar, at %s',
    async (address) => {
      // The page's lists are asked for while the project loads; the server knows none of them.
      mockFetch([
        { path: '/api/v1/projects/prj_missing', respond: () => errorResponse(404, 'not_found', 'Unknown project prj_missing') },
        { path: '/api/v1/projects/prj_missing/clarifications', respond: () => errorResponse(404, 'not_found', 'Unknown project prj_missing') },
      ]);
      renderApp(address);
      expect(await screen.findByRole('heading', { level: 2, name: 'There is nothing at this address' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument();
      expect(screen.getByText('This project does not exist.')).toBeInTheDocument();
      expect(screen.queryByText(/No page matches/)).not.toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Go to projects' })).toHaveAttribute('href', '/projects');
      // No such project: no bar with its pages.
      expect(screen.queryByRole('navigation', { name: 'Project' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    },
  );

  it.each([
    ['/documents', '/projects/prj_1/workspace?document=doc_1'],
    ['/runs', '/projects/prj_1/workspace?tab=requirements&document=doc_1'],
    ['/runs/run_2', '/projects/prj_1/workspace?tab=requirements&run=run_2&document=doc_1'],
    ['/issues', '/projects/prj_1/workspace?tab=issues&document=doc_1'],
    ['/issues?run=run_2&severity=high', '/projects/prj_1/workspace?tab=issues&run=run_2&document=doc_1'],
    ['/issues/iss_1?run=run_2', '/projects/prj_1/workspace?tab=issues&run=run_2&issue=iss_1&document=doc_1'],
    ['/exports', '/projects/prj_1/workspace?tab=export&document=doc_1'],
    ['/exports?run=run_1', '/projects/prj_1/workspace?tab=export&run=run_1&document=doc_1'],
  ])('sends the old address %s to %s', async (from, to) => {
    mockFetch([{ path: '/api/v1/documents/doc_1', respond: pendingUntilAborted }, ...projectWorkspaceRoutes().slice(-3)]);
    const { location } = renderApp(from, { activeDocumentId: 'doc_1' });
    await waitFor(() => expect(location()).toBe(to));
    expect(screen.getByText('Loading the file…')).toBeInTheDocument();
  });

  it('opens the document of an old /documents/:documentId address in the Workspace of its project', async () => {
    const api = mockFetch([
      { path: '/api/v1/documents/doc_2', respond: pendingUntilAborted },
      { path: '/api/v1/projects/prj_1', respond: pendingUntilAborted },
      { path: '/api/v1/projects', respond: [{ ...WORKSPACE_PROJECT, files: [{ document_id: 'doc_2', role: 'bill' }] }] },
    ]);
    const { location } = renderApp('/documents/doc_2');

    await waitFor(() => expect(location()).toBe('/projects/prj_1/workspace?document=doc_2'));
    expect(window.localStorage.getItem(ACTIVE_DOCUMENT_STORAGE_KEY)).toBe('doc_2');
    await waitFor(() => expect(api.callsTo('GET', '/api/v1/documents/doc_2').length).toBeGreaterThan(0));
  });
});
