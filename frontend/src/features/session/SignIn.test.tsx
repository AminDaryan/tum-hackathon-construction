import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ACCESS_TOKEN_STORAGE_KEY } from '../../services/accessToken.ts';
import { DEFAULT_HEALTH, errorResponse, mockFetch, type MockCall, type MockRoute } from '../../test/fetchMock.ts';
import { health, profiles } from '../../test/fixtures.ts';
import { renderApp } from '../../test/render.tsx';
import type { UserEvent } from '@testing-library/user-event';

const TOKEN = 'tok-3f9c-secret';
const unauthorized = () =>
  errorResponse(401, 'unauthorized', 'A valid access token is required.', { requestId: 'req_auth' });

/** A server that requires `TOKEN` on every route but /health. */
function protectedRoutes(extra: MockRoute[] = []): MockRoute[] {
  const guard = (respond: (call: MockCall) => unknown) => (call: MockCall) =>
    call.headers.get('Authorization') === `Bearer ${TOKEN}` ? respond(call) : unauthorized();
  return [
    { path: '/api/v1/health', respond: { ...DEFAULT_HEALTH, auth_required: true } },
    { path: '/api/v1/profiles', respond: guard(() => profiles) },
    { path: '/api/v1/projects', respond: guard(() => []) },
    ...extra,
  ];
}

async function signIn(user: UserEvent, token: string) {
  const field = await screen.findByLabelText('Access token');
  await user.clear(field);
  await user.type(field, token);
  await user.click(screen.getByRole('button', { name: 'Sign in' }));
}

describe('Sign-in', () => {
  it('asks for a token before calling protected routes and then sends it with every request', async () => {
    const api = mockFetch(protectedRoutes());
    const { user } = renderApp('/projects');

    const dialog = await screen.findByRole('dialog', { name: 'Sign in to Desvio' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    const field = screen.getByLabelText('Access token');
    expect(field).toHaveFocus();
    expect(field).toHaveAttribute('type', 'password');
    expect(api.calls.map((call) => call.path)).toEqual(['/api/v1/health']);

    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Enter your access token.');

    await signIn(user, 'wrong-token');
    expect(await screen.findByText('This access token was not accepted. Check it and try again.')).toBeInTheDocument();
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();

    await signIn(user, TOKEN);
    await screen.findByText('No projects yet');
    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe(TOKEN);
    expect(window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
    expect(api.callsTo('GET', '/api/v1/projects').at(-1)!.headers.get('Authorization')).toBe(`Bearer ${TOKEN}`);
    expect(document.body.textContent).not.toContain(TOKEN);
  });

  it('asks again when the server rejects the stored token', async () => {
    let valid = true;
    const api = mockFetch([
      { path: '/api/v1/health', respond: { ...DEFAULT_HEALTH, auth_required: true } },
      { path: '/api/v1/profiles', respond: (call) => (call.headers.get('Authorization') === 'Bearer fresh' ? profiles : unauthorized()) },
      { path: '/api/v1/projects', respond: () => (valid ? [] : unauthorized()) },
    ]);
    window.sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'stale');
    valid = false;
    const { user } = renderApp('/projects');

    expect(
      await screen.findByText('The server did not accept your access token, or it is no longer valid. Enter it again.'),
    ).toBeInTheDocument();
    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
    valid = true;
    await signIn(user, 'fresh');
    await screen.findByText('No projects yet');
    expect(api.callsTo('GET', '/api/v1/projects').at(-1)!.headers.get('Authorization')).toBe('Bearer fresh');
  });

  it('signs out from the user menu', async () => {
    mockFetch(protectedRoutes());
    window.sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, TOKEN);
    const { user } = renderApp('/projects');

    await user.click(await screen.findByRole('button', { name: /^Open the user menu/ }));
    await user.click(screen.getByRole('menuitem', { name: 'Log out' }));

    expect(await screen.findByRole('dialog', { name: 'Sign in to Desvio' })).toBeInTheDocument();
    expect(screen.getByText('You signed out. Enter an access token to continue.')).toBeInTheDocument();
    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
  });

  it('does not ask or send a token when the server does not require one', async () => {
    const api = mockFetch([
      { path: '/api/v1/health', respond: health },
      { path: '/api/v1/projects', respond: [] },
    ]);
    renderApp('/projects');
    await screen.findByText('No projects yet');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    // The page's table and the sidebar's list.
    await waitFor(() => expect(api.callsTo('GET', '/api/v1/projects')).toHaveLength(2));
    expect(api.calls.every((call) => !call.headers.has('Authorization'))).toBe(true);
  });

  it('starts the application when the health check fails', async () => {
    mockFetch([{ path: '/api/v1/health', respond: errorResponse(500, 'internal_error', 'Unexpected failure.') }]);
    renderApp('/no/such/page');
    expect(await screen.findByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument();
  });

  it('says when a token cannot be checked because the server is unreachable', async () => {
    mockFetch([
      { path: '/api/v1/health', respond: { ...DEFAULT_HEALTH, auth_required: true } },
      {
        path: '/api/v1/profiles',
        respond: () => {
          throw new TypeError('Failed to fetch');
        },
      },
    ]);
    const { user } = renderApp('/projects');
    await signIn(user, TOKEN);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The token could not be checked: The server could not be reached. Check that the backend is running, then try again.',
    );
    expect(screen.getByRole('alert')).not.toHaveTextContent(TOKEN);
  });

  it('shows in Settings which profile is the default, with no word on sign-in', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }, { path: '/api/v1/detectors', respond: { items: [] } }]);
    renderApp('/settings?tab=system');
    expect(await screen.findByText('Default profile')).toBeInTheDocument();
    expect(screen.queryByText(/sign-in/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
    expect(screen.getByText('Default profile').nextElementSibling ?? screen.getByText('Default profile').parentElement).toHaveTextContent('boq');
  });
});
