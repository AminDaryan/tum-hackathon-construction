import { SearchField } from '../../components/Field.tsx';
import { Select } from '../../components/Select.tsx';
import { useI18n } from '../../i18n/useI18n.ts';
import { ROLES } from '../profile/roles.ts';
import type { UserFilters } from './userFilters.ts';

interface UserFilterBarProps {
  filters: UserFilters;
  onChange: (filters: UserFilters) => void;
  disabled?: boolean;
}

/** Above the accounts table: the search, and the role and status filters. */
export function UserFilterBar({ filters, onChange, disabled = false }: UserFilterBarProps) {
  const { t } = useI18n();
  const change = (next: Partial<UserFilters>) => onChange({ ...filters, ...next });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchField
        label={t('users.search')}
        placeholder={t('users.search')}
        autoComplete="off"
        value={filters.search}
        onChange={(search) => change({ search })}
        isDisabled={disabled}
        className="min-w-48 max-w-sm flex-1"
      />
      <Select
        label={t('users.column.role')}
        hideLabel
        value={filters.role}
        // The select offers only ROLES.
        onChange={(role) => change({ role: role as UserFilters['role'] })}
        options={[{ value: '', label: t('users.allRoles') }, ...ROLES.map((role) => ({ value: role, label: t(`role.${role}`) }))]}
        disabled={disabled}
      />
      <Select
        label={t('users.column.status')}
        hideLabel
        value={filters.status}
        // The select offers only these three.
        onChange={(status) => change({ status: status as UserFilters['status'] })}
        options={[
          { value: '', label: t('users.allStatuses') },
          { value: 'active', label: t('users.active') },
          { value: 'inactive', label: t('users.inactive') },
        ]}
        disabled={disabled}
      />
    </div>
  );
}
