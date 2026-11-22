/** The search and filters over the user accounts table, without React. */
import { matchesSearch } from '../../utils/textSearch.ts';
import type { UserAccount } from '../../services/apiTypes.ts';

export interface UserFilters {
  /** words found in the name, the email or the job title */
  search: string;
  /** '' for every role */
  role: '' | UserAccount['role'];
  /** '' for every account */
  status: '' | 'active' | 'inactive';
}

export const NO_USER_FILTERS: Readonly<UserFilters> = Object.freeze({ search: '', role: '', status: '' });

/** The accounts that meet every filter, in their order. */
export function filterUsers(users: readonly UserAccount[], filters: UserFilters): UserAccount[] {
  return users.filter(
    (user) =>
      (!filters.role || user.role === filters.role) &&
      (!filters.status || user.active === (filters.status === 'active')) &&
      matchesSearch(filters.search, [user.name, user.email, user.job_title]),
  );
}
