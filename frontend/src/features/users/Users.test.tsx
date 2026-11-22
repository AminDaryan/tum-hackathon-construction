import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DEFAULT_ME, errorResponse, mockFetch } from '../../test/fetchMock.ts';
import { renderApp } from '../../test/render.tsx';
import { getSelect } from '../../test/select.ts';
import type { UserEvent } from '@testing-library/user-event';

const ADA = Object.freeze({
  user_id: 'usr_1',
  name: 'Ada',
  first_name: 'Ada',
  last_name: '',
  job_title: '',
  phone: '',
  email: 'ada@example.test',
  role: 'admin',
  active: true,
  created_at: '2026-11-20T09:00:00Z',
  token_hint: 'x7Qa',
  token_issued_at: '2026-11-20T09:00:00Z',
});
const BERT = Object.freeze({
  ...ADA,
  user_id: 'usr_2',
  name: 'Bert Klein',
  first_name: 'Bert',
  last_name: 'Klein',
  job_title: 'Estimator',
  phone: '+49 30 1234',
  email: '',
  role: 'reviewer',
  token_hint: 'k2Pz',
});

/** Picks an option of a select (a button that opens a listbox). */
async function choose(user: UserEvent, trigger: HTMLElement, option: string) {
  await user.click(trigger);
  await user.click(await screen.findByRole('option', { name: option }));
}

const roleSelect = () => getSelect('Role');

describe('Users', () => {
  it('searches the accounts and filters them by role and status', async () => {
    mockFetch([{ path: '/api/v1/users', respond: [ADA, BERT, { ...BERT, user_id: 'usr_4', name: 'Cleo Weber', role: 'viewer', active: false }] }]);
    const { user } = renderApp('/users');
    expect(await screen.findByText('ada@example.test')).toBeInTheDocument();
    const heading = () => screen.getByRole('heading', { name: /^User accounts/ });
    expect(heading()).toHaveTextContent('(3)');

    await user.type(screen.getByRole('searchbox', { name: 'Search users' }), 'klein');
    expect(heading()).toHaveTextContent('(1)');
    expect(within(screen.getByRole('main')).getByText('Bert Klein')).toBeInTheDocument();
    await user.clear(screen.getByRole('searchbox', { name: 'Search users' }));

    await choose(user, getSelect('Role'), 'Viewer');
    expect(heading()).toHaveTextContent('(1)');
    expect(within(screen.getByRole('main')).getByText('Cleo Weber')).toBeInTheDocument();
    await choose(user, getSelect('Status'), 'Active');
    expect(screen.getByText('No accounts match the search and filters')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(heading()).toHaveTextContent('(3)');
  });

  it('deactivates and activates an account in its row, and keeps one\'s own account a badge', async () => {
    let bert: typeof BERT = BERT;
    const api = mockFetch([
      { path: '/api/v1/me', respond: { ...DEFAULT_ME, kind: 'user', name: 'Ada', user_id: 'usr_1' } },
      { path: '/api/v1/users', respond: () => [ADA, bert] },
      { method: 'PATCH', path: '/api/v1/users/usr_2', respond: (call) => (bert = { ...bert, ...JSON.parse(call.body) }) },
    ]);
    const { user, location } = renderApp('/users');
    const table = await screen.findByRole('grid', { name: /^User accounts/ });
    await within(table).findByRole('button', { name: 'Active Status of Bert Klein' });
    expect(within(table).queryByRole('button', { name: /Status of Ada/ })).not.toBeInTheDocument();

    await user.click(within(table).getByRole('button', { name: 'Active Status of Bert Klein' }));
    await user.click(await screen.findByRole('option', { name: 'Deactivated' }));
    expect(await within(table).findByRole('button', { name: 'Deactivated Status of Bert Klein' })).toBeInTheDocument();
    await user.click(within(table).getByRole('button', { name: 'Deactivated Status of Bert Klein' }));
    await user.click(await screen.findByRole('option', { name: 'Active' }));
    expect(await within(table).findByRole('button', { name: 'Active Status of Bert Klein' })).toBeInTheDocument();
    expect(api.callsTo('PATCH', '/api/v1/users/usr_2').map((call) => JSON.parse(call.body))).toEqual([{ active: false }, { active: true }]);
    expect(location()).toBe('/users');
  });

  it('lists the accounts and creates one whose token is shown once', async () => {
    const api = mockFetch([
      { path: '/api/v1/users', respond: [ADA] },
      {
        method: 'POST',
        path: '/api/v1/users',
        respond: (call) => {
          const body = JSON.parse(call.body);
          const name = `${body.first_name} ${body.last_name}`;
          return { user: { ...BERT, ...body, name, user_id: 'usr_3', token_hint: 'AbCd' }, token: 'twb_secretAbCd' };
        },
      },
    ]);
    const { user } = renderApp('/users');

    // Wait for the loaded list: the placeholder shown while loading has a heading of the same name.
    expect(await screen.findByText('ada@example.test')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /^User accounts/ })).toBeInTheDocument();
    expect(screen.getByText('ends in x7Qa')).toBeInTheDocument();
    // No notice about how the server is set up.
    expect(screen.queryByText(/Sign-in is off/)).not.toBeInTheDocument();

    await user.click(within(screen.getByRole('main')).getByRole('button', { name: 'Add user' }));
    const form = screen.getByRole('form', { name: 'New user' });
    await user.click(within(form).getByRole('button', { name: 'Create user' }));
    expect(within(form).getByText('Enter a name.')).toBeInTheDocument();
    expect(within(form).getByLabelText('First name')).toHaveFocus();

    await user.type(within(form).getByLabelText('First name'), 'Carla');
    await user.type(within(form).getByLabelText('Last name'), 'Weber');
    await user.type(within(form).getByLabelText('Email (optional)'), 'not-an-email');
    await user.click(within(form).getByRole('button', { name: 'Create user' }));
    expect(within(form).getByText(/Enter an email address/)).toBeInTheDocument();
    await user.clear(within(form).getByLabelText('Email (optional)'));
    await user.type(within(form).getByLabelText('Email (optional)'), 'carla@example.test');
    await choose(user, within(form).getByRole('button', { name: /Role/ }), 'Viewer');
    await user.click(within(form).getByRole('button', { name: 'Create user' }));

    const issued = await screen.findByRole('region', { name: 'Access token for Carla Weber' });
    expect(within(issued).getByTestId('issued-token')).toHaveTextContent('twb_secretAbCd');
    expect(JSON.parse(api.callsTo('POST', '/api/v1/users')[0].body)).toEqual({
      first_name: 'Carla',
      last_name: 'Weber',
      email: 'carla@example.test',
      role: 'viewer',
    });
    expect(screen.getByText('carla@example.test')).toBeInTheDocument();
    await user.click(within(issued).getByRole('button', { name: 'Done' }));
    expect(screen.queryByText('twb_secretAbCd')).not.toBeInTheDocument();
  });

  it('opens a user from the table on the user\'s own page, with the details of the account', async () => {
    mockFetch([{ path: '/api/v1/users', respond: [ADA, BERT] }]);
    const { user, location } = renderApp('/users');

    expect(await screen.findByRole('heading', { level: 1, name: 'Users' })).toBeInTheDocument();
    const table = await screen.findByRole('grid', { name: /^User accounts/ });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringMatching(/Adaada@example\.testAdministratorActive/),
      expect.stringMatching(/Bert KleinNo email addressReviewerActive/),
    ]);
    // In the table only the status is changed; everything else on the user's page.
    expect(within(table).getAllByRole('button').map((button) => button.getAttribute('aria-label'))).toEqual(['Status of Ada', 'Status of Bert Klein']);

    await user.click(within(rows[1]).getByText('Bert Klein'));
    await waitFor(() => expect(location()).toBe('/users/usr_2'));
    expect(await screen.findByRole('heading', { level: 1, name: 'Bert Klein' })).toBeInTheDocument();
    const account = screen.getByRole('region', { name: 'Bert Klein' });
    for (const [label, value] of [
      ['First name', 'Bert'],
      ['Last name', 'Klein'],
      ['Job title', 'Estimator'],
      ['Phone', '+49 30 1234'],
      ['Status', 'Active'],
    ]) {
      expect(within(account).getByText(label).nextElementSibling).toHaveTextContent(value);
    }
    expect(within(account).getByText('Access token').nextElementSibling).toHaveTextContent('ends in k2Pz');

    await user.click(screen.getByRole('button', { name: 'Back to all users' }));
    await waitFor(() => expect(location()).toBe('/users'));
  });

  it('changes a role, deactivates, issues a new token and deletes after confirming, on the user\'s page', async () => {
    let bert = BERT;
    let deleted = false;
    const api = mockFetch([
      { path: '/api/v1/users', respond: () => (deleted ? [ADA] : [ADA, bert]) },
      {
        method: 'PATCH',
        path: '/api/v1/users/usr_2',
        respond: (call) => {
          bert = { ...bert, ...JSON.parse(call.body) };
          return bert;
        },
      },
      { method: 'POST', path: '/api/v1/users/usr_2/token', respond: () => ({ user: { ...bert, token_hint: 'NeW1' }, token: 'twb_freshNeW1' }) },
      {
        method: 'DELETE',
        path: '/api/v1/users/usr_2',
        respond: () => {
          deleted = true;
          return [ADA];
        },
      },
    ]);
    const { user, location } = renderApp('/users/usr_2');

    const account = await screen.findByRole('region', { name: 'Bert Klein' });
    await choose(user, roleSelect(), 'Viewer');
    await waitFor(() => expect(JSON.parse(api.callsTo('PATCH', '/api/v1/users/usr_2')[0].body)).toEqual({ role: 'viewer' }));
    await waitFor(() => expect(roleSelect()).toHaveTextContent('Viewer'));

    await user.click(within(account).getByRole('button', { name: 'Deactivate' }));
    expect(await within(account).findByText('Deactivated')).toBeInTheDocument();
    expect(within(account).getByRole('button', { name: 'Activate' })).toBeInTheDocument();

    await user.click(within(account).getByRole('button', { name: 'New token' }));
    expect(await screen.findByTestId('issued-token')).toHaveTextContent('twb_freshNeW1');
    expect(within(account).getByText('Access token').nextElementSibling).toHaveTextContent('ends in NeW1');

    await user.click(within(account).getByRole('button', { name: 'Delete' }));
    const confirm = screen.getByRole('alertdialog', { name: 'Delete Bert Klein' });
    await user.click(within(confirm).getByRole('button', { name: 'Delete user' }));
    // Back on the table, without the account.
    await waitFor(() => expect(location()).toBe('/users'));
    expect(await screen.findByText('ada@example.test')).toBeInTheDocument();
    expect(screen.queryByText('Bert Klein')).not.toBeInTheDocument();
    expect(api.callsTo('DELETE', '/api/v1/users/usr_2')).toHaveLength(1);
  });

  it('edits a user\'s details on their page and sends only the changed fields', async () => {
    let bert = BERT;
    const api = mockFetch([
      { path: '/api/v1/users', respond: () => [ADA, bert] },
      {
        method: 'PATCH',
        path: '/api/v1/users/usr_2',
        respond: (call) => {
          const changes = JSON.parse(call.body);
          bert = { ...bert, ...changes, name: `${changes.first_name ?? bert.first_name} ${changes.last_name ?? bert.last_name}`.trim() };
          return bert;
        },
      },
    ]);
    const { user } = renderApp('/users/usr_2');
    const account = await screen.findByRole('region', { name: 'Bert Klein' });

    // Cancel closes the form without saving.
    await user.click(within(account).getByRole('button', { name: 'Edit' }));
    await user.click(within(screen.getByRole('form', { name: 'Personal details' })).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('form', { name: 'Personal details' })).not.toBeInTheDocument();

    await user.click(within(account).getByRole('button', { name: 'Edit' }));
    const form = screen.getByRole('form', { name: 'Personal details' });
    await user.clear(within(form).getByLabelText(/First name/));
    await user.click(within(form).getByRole('button', { name: 'Save changes' }));
    expect(within(form).getByText('Enter a name.')).toBeInTheDocument();
    expect(api.callsTo('PATCH', '/api/v1/users/usr_2')).toHaveLength(0);

    await user.type(within(form).getByLabelText(/First name/), 'Berta');
    await user.clear(within(form).getByLabelText('Phone'));
    await user.type(within(form).getByLabelText('Email'), 'berta@example.test');
    await user.click(within(form).getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByRole('region', { name: 'Berta Klein' })).toBeInTheDocument();
    expect(JSON.parse(api.callsTo('PATCH', '/api/v1/users/usr_2')[0].body)).toEqual({
      first_name: 'Berta',
      email: 'berta@example.test',
      phone: '',
    });
    expect(screen.queryByRole('form', { name: 'Personal details' })).not.toBeInTheDocument();
    expect(screen.getByText('Job title').nextElementSibling).toHaveTextContent('Estimator');
    expect(screen.getByText('Email').nextElementSibling).toHaveTextContent('berta@example.test');
  });

  it('does not let a signed-in administrator demote, deactivate or delete themselves', async () => {
    mockFetch([
      { path: '/api/v1/me', respond: { ...DEFAULT_ME, kind: 'user', name: 'Ada', user_id: 'usr_1' } },
      { path: '/api/v1/users', respond: [ADA, BERT] },
    ]);
    renderApp('/users/usr_1');
    const account = await screen.findByRole('region', { name: 'Ada' });
    expect(within(account).getByText('You')).toBeInTheDocument();
    expect(roleSelect()).toBeDisabled();
    expect(within(account).getByRole('button', { name: 'New token' })).toBeInTheDocument();
    expect(within(account).queryByRole('button', { name: 'Deactivate' })).not.toBeInTheDocument();
    expect(within(account).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('reports a refused change', async () => {
    mockFetch([
      { path: '/api/v1/users', respond: [ADA, BERT] },
      { method: 'PATCH', path: '/api/v1/users/usr_2', respond: errorResponse(409, 'conflict', 'You cannot deactivate your own account.') },
    ]);
    const { user } = renderApp('/users/usr_2');
    await user.click(await screen.findByRole('button', { name: 'Deactivate' }));
    expect(await screen.findByText('The change was not saved')).toBeInTheDocument();
    expect(screen.getByText('You cannot deactivate your own account.')).toBeInTheDocument();
  });

  it('goes back to the table for an account that does not exist', async () => {
    mockFetch([{ path: '/api/v1/users', respond: [ADA] }]);
    const { location } = renderApp('/users/usr_9');
    await waitFor(() => expect(location()).toBe('/users'));
    expect(await screen.findByText('ada@example.test')).toBeInTheDocument();
  });

  it('tells everyone but administrators that only administrators manage accounts', async () => {
    const api = mockFetch([
      {
        path: '/api/v1/me',
        respond: { ...DEFAULT_ME, kind: 'user', name: 'Bert', role: 'reviewer', user_id: 'usr_2', permissions: ['read', 'write'] },
      },
    ]);
    renderApp('/users');
    expect(await screen.findByText('Only administrators manage user accounts')).toBeInTheDocument();
    expect(screen.getByText(/You are signed in as Bert \(Reviewer\)/)).toBeInTheDocument();
    expect(api.callsTo('GET', '/api/v1/users')).toHaveLength(0);
  });
});
