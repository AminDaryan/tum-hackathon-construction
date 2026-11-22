import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ACCESS_TOKEN_STORAGE_KEY } from '../../services/accessToken.ts';
import { DEFAULT_ME, mockFetch } from '../../test/fetchMock.ts';
import { renderApp } from '../../test/render.tsx';
import type { Me, UserAccount } from '../../services/apiTypes.ts';

const ACCOUNT = Object.freeze<UserAccount>({
  user_id: 'usr_2',
  name: 'Vera Kühn',
  first_name: 'Vera',
  last_name: 'Kühn',
  email: 'vera@example.test',
  job_title: 'Quantity surveyor',
  phone: '',
  role: 'viewer',
  active: true,
  created_at: '2026-11-20T09:00:00Z',
  token_hint: 'eN0c',
  token_issued_at: '2026-11-20T09:00:00Z',
});

function meOf(account: UserAccount): Me {
  return {
    kind: 'user',
    name: account.name,
    email: account.email,
    role: account.role,
    user_id: account.user_id,
    auth_required: false,
    permissions: ['read'],
    account,
  };
}

describe('Settings, My profile', () => {
  it('shows the details, role and access of a user and saves their changes', async () => {
    let account = ACCOUNT;
    const api = mockFetch([{ path: '/api/v1/projects', respond: [] }, 
      { path: '/api/v1/me', respond: () => meOf(account) },
      {
        method: 'PATCH',
        path: '/api/v1/me',
        respond: (call) => {
          const changes = JSON.parse(call.body);
          account = { ...account, ...changes, name: `${changes.first_name ?? account.first_name} ${account.last_name}` };
          return meOf(account);
        },
      },
    ]);
    const { user } = renderApp('/settings?tab=profile');

    const form = await screen.findByRole('form', { name: 'Personal details' });
    expect(within(form).getByLabelText(/First name/)).toHaveValue('Vera');
    expect(within(form).getByLabelText('Last name')).toHaveValue('Kühn');
    expect(within(form).getByLabelText('Email')).toHaveValue('vera@example.test');
    expect(within(form).getByLabelText('Job title')).toHaveValue('Quantity surveyor');
    expect(within(form).getByRole('button', { name: 'Save changes' })).toBeDisabled();
    expect(screen.getByText('Quantity surveyor, vera@example.test')).toBeInTheDocument();
    expect(screen.getByText('Only an administrator can change your role or deactivate your account.')).toBeInTheDocument();
    expect(screen.getByText('Reads bills, findings and reports; changes nothing.')).toBeInTheDocument();
    expect(screen.getByText('ends in eN0c')).toBeInTheDocument();
    expect(screen.getByText('Member since')).toBeInTheDocument();

    await user.type(within(form).getByLabelText('Phone'), 'call me');
    await user.click(within(form).getByRole('button', { name: 'Save changes' }));
    expect(within(form).getByText('Use digits, spaces and + ( ) - / . only.')).toBeInTheDocument();
    expect(within(form).getByLabelText('Phone')).toHaveFocus();
    expect(api.callsTo('PATCH', '/api/v1/me')).toHaveLength(0);

    await user.clear(within(form).getByLabelText('Phone'));
    await user.type(within(form).getByLabelText('Phone'), '+49 30 1234-56');
    await user.clear(within(form).getByLabelText(/First name/));
    await user.type(within(form).getByLabelText(/First name/), 'Veronika');
    await user.click(within(form).getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByText('Your profile is saved.')).toBeInTheDocument();
    expect(JSON.parse(api.callsTo('PATCH', '/api/v1/me')[0].body)).toEqual({ first_name: 'Veronika', phone: '+49 30 1234-56' });
    const avatar = await screen.findByRole('button', { name: 'Open the user menu of Veronika Kühn', hidden: true });
    expect(avatar).toBeInTheDocument();
    expect(within(form).getByRole('button', { name: 'Save changes' })).toBeDisabled();
  });

  it('does not tell an administrator that only an administrator can change their role', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }, { path: '/api/v1/me', respond: meOf({ ...ACCOUNT, role: 'admin' }) }]);
    renderApp('/settings?tab=profile');

    expect(await screen.findByText('Everything a reviewer can do, and manages the user accounts.')).toBeInTheDocument();
    expect(screen.queryByText(/Only an administrator can change your role/)).not.toBeInTheDocument();
  });

  it('asks for a first name and undoes changes', async () => {
    const api = mockFetch([{ path: '/api/v1/projects', respond: [] }, { path: '/api/v1/me', respond: meOf(ACCOUNT) }]);
    const { user } = renderApp('/settings?tab=profile');
    const form = await screen.findByRole('form', { name: 'Personal details' });
    await user.clear(within(form).getByLabelText(/First name/));
    await user.click(within(form).getByRole('button', { name: 'Save changes' }));
    expect(within(form).getByText('Enter your first name.')).toBeInTheDocument();
    await user.click(within(form).getByRole('button', { name: 'Undo changes' }));
    expect(within(form).getByLabelText(/First name/)).toHaveValue('Vera');
    expect(api.callsTo('PATCH', '/api/v1/me')).toHaveLength(0);
  });

  it('lets the local administrator sign in to their own profile', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }, 
      {
        path: '/api/v1/me',
        respond: (call) => (call.headers.get('Authorization') === 'Bearer twb_vera' ? meOf(ACCOUNT) : DEFAULT_ME),
      },
    ]);
    const { user } = renderApp('/settings?tab=profile');

    expect(await screen.findByLabelText('Personal access token')).toBeInTheDocument();
    expect(screen.queryByText(/Sign-in is off/)).not.toBeInTheDocument();
    expect(screen.queryByRole('form', { name: 'Personal details' })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Personal access token'), 'twb_typo');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This token does not belong to an active user account.');

    await user.clear(screen.getByLabelText('Personal access token'));
    await user.type(screen.getByLabelText('Personal access token'), 'twb_vera');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('form', { name: 'Personal details' })).toBeInTheDocument();
    await waitFor(() => expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe('twb_vera'));
    expect(document.body.textContent).not.toContain('twb_vera');
  });
});
