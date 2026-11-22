import { describe, expect, it } from 'vitest';
import { filterUsers, NO_USER_FILTERS } from './userFilters.ts';
import type { UserAccount } from '../../services/apiTypes.ts';

function account(user_id: string, overrides: Partial<UserAccount> = {}): UserAccount {
  return {
    user_id,
    name: user_id,
    first_name: user_id,
    last_name: '',
    email: '',
    job_title: '',
    phone: '',
    role: 'reviewer',
    active: true,
    created_at: '2026-11-20T09:00:00Z',
    token_hint: null,
    token_issued_at: null,
    ...overrides,
  };
}

const USERS = [
  account('ada', { name: 'Ada Lovelace', email: 'ada@example.test', role: 'admin' }),
  account('bert', { name: 'Bert Klein', job_title: 'Estimator' }),
  account('cleo', { name: 'Cleo Weber', role: 'viewer', active: false }),
];
const ids = (users: UserAccount[]) => users.map((user) => user.user_id);

describe('filterUsers', () => {
  it('searches the name, the email and the job title', () => {
    expect(ids(filterUsers(USERS, NO_USER_FILTERS))).toEqual(['ada', 'bert', 'cleo']);
    expect(ids(filterUsers(USERS, { ...NO_USER_FILTERS, search: 'example.test' }))).toEqual(['ada']);
    expect(ids(filterUsers(USERS, { ...NO_USER_FILTERS, search: 'estimator' }))).toEqual(['bert']);
  });

  it('filters by role and by active or deactivated', () => {
    expect(ids(filterUsers(USERS, { ...NO_USER_FILTERS, role: 'viewer' }))).toEqual(['cleo']);
    expect(ids(filterUsers(USERS, { ...NO_USER_FILTERS, status: 'active' }))).toEqual(['ada', 'bert']);
    expect(ids(filterUsers(USERS, { ...NO_USER_FILTERS, status: 'inactive' }))).toEqual(['cleo']);
    expect(ids(filterUsers(USERS, { search: 'ada', role: 'reviewer', status: '' }))).toEqual([]);
  });
});
