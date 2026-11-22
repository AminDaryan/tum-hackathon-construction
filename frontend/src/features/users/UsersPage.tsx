import { RotateCw, UserCheck, UserPlus, UserX } from 'lucide-react';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { refreshSidebarLists } from '../../app/sidebarLists.ts';
import type { DataTableColumn } from '../../components/DataTable.tsx';
import { Badge } from '../../components/Badge.tsx';
import { Button } from '../../components/Button.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { StatusSelect, type StatusOption } from '../../components/StatusSelect.tsx';
import { TableCard, usePagedRows } from '../../components/TableCard.tsx';
import { Timestamp } from '../../components/Timestamp.tsx';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { useI18n } from '../../i18n/useI18n.ts';
import type { IssuedToken as Issued, UserAccount } from '../../services/apiTypes.ts';
import { listUsers, updateUser } from '../../services/usersService.ts';
import { useSession } from '../../stores/useSession.ts';
import { cx } from '../../utils/classNames.ts';
import { Avatar } from '../profile/Avatar.tsx';
import { RoleBadge } from '../profile/ProfileParts.tsx';
import { AddUserForm, AdminOnlyNotice, IssuedToken } from './userParts.tsx';
import { UserFilterBar } from './UserFilterBar.tsx';
import { filterUsers, NO_USER_FILTERS, type UserFilters } from './userFilters.ts';

/** Accounts per page. */
const PAGE_SIZE = 10;
const noop = () => {};

interface UserColumnsOptions {
  /** the account of the person signed in: marked "You", its status not changed here */
  selfId?: string | null;
  /** a change is being saved */
  saving?: boolean;
  /** changes whether an account is active; without it the status is a badge */
  onActiveChange?: (user: UserAccount, active: boolean) => void;
}

/** The columns of the accounts table: who, the role, the status and the token. */
function useUserColumns({ selfId = null, saving = false, onActiveChange }: UserColumnsOptions = {}): DataTableColumn<UserAccount>[] {
  const { t } = useI18n();
  const statuses: StatusOption<'active' | 'inactive'>[] = [
    { value: 'active', label: t('users.active'), icon: UserCheck, tone: 'accent' },
    { value: 'inactive', label: t('users.inactive'), icon: UserX, tone: 'neutral' },
  ];
  return [
    {
      key: 'user',
      placeholderWidth: 'w-44',
      header: t('users.column.user'),
      render: (user) => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={user.name} role={user.role} className={cx(!user.active && 'opacity-50')} />
          <div className="min-w-0">
            <p className="flex items-center gap-2 truncate text-callout font-medium text-ink">
              {user.name}
              {user.user_id === selfId && <Badge tone="accent">{t('users.you')}</Badge>}
            </p>
            <p className="truncate text-caption text-ink-secondary">{user.email || t('profile.noEmail')}</p>
          </div>
        </div>
      ),
    },
    { key: 'role', placeholderWidth: 'w-24', header: t('users.column.role'), render: (user) => <RoleBadge role={user.role} /> },
    {
      key: 'status',
      placeholderWidth: 'w-16',
      header: t('users.column.status'),
      render: (user) => (
        <StatusSelect
          label={t('users.statusOf', { name: user.name })}
          value={user.active ? 'active' : 'inactive'}
          options={statuses}
          onChange={(status) => onActiveChange?.(user, status === 'active')}
          // One's own account cannot be deactivated.
          readOnly={!onActiveChange || user.user_id === selfId}
          disabled={saving}
        />
      ),
    },
    {
      key: 'token',
      placeholderWidth: 'w-24',
      header: t('users.column.token'),
      className: 'text-caption text-ink-secondary',
      render: (user) =>
        user.token_hint ? (
          <>
            <span className="font-mono text-ink">{t('users.tokenEnding', { hint: user.token_hint })}</span>
            <span className="block">
              <Timestamp value={user.token_issued_at} />
            </span>
          </>
        ) : (
          t('users.noToken')
        ),
    },
  ];
}

/** The accounts, for administrators: the table, and adding an account. A row opens the user. */
function UserAdministration() {
  const { t } = useI18n();
  const { me } = useSession();
  const navigate = useNavigate();
  const users = useApiResource((signal) => listUsers(signal), []);
  // In the address, so the + beside Users in the sidebar opens it too.
  const [searchParams, setSearchParams] = useSearchParams();
  const adding = searchParams.has('add');
  const setAdding = (open: boolean) => setSearchParams(open ? { add: '1' } : {}, { replace: !open });
  const [issued, setIssued] = useState<Issued | null>(null);
  const change = useAsyncAction((signal, userId: string, active: boolean) => updateUser(userId, { active }, signal));
  const columns = useUserColumns({
    selfId: me?.user_id,
    saving: change.pending,
    onActiveChange: async (user, active) => {
      const saved = await change.execute(user.user_id, active);
      if (saved) users.setData((current) => current?.map((candidate) => (candidate.user_id === saved.user_id ? saved : candidate)));
    },
  });
  const [filters, setFilters] = useState<UserFilters>(NO_USER_FILTERS);
  const shown = users.data ? filterUsers(users.data, filters) : null;
  const page = usePagedRows(shown ?? [], PAGE_SIZE);
  const changeFilters = (next: UserFilters) => {
    setFilters(next);
    page.setOffset(0);
  };
  const noMatch = Boolean(users.data?.length) && shown?.length === 0;

  let status: string | null = null;
  if (users.error) status = t('users.loadFailed');
  else if (users.data?.length === 0) status = t('users.empty');
  else if (noMatch) status = t('users.noMatch');

  return (
    <div className="flex flex-col gap-5">
      {issued && <IssuedToken issued={issued} onDismiss={() => setIssued(null)} />}
      {change.error && <ErrorState error={change.error} title={t('users.actionFailed')} compact />}
      {adding && (
        <AddUserForm
          onCancel={() => setAdding(false)}
          onCreated={(result) => {
            setAdding(false);
            setIssued(result);
            refreshSidebarLists();
            users.setData((current) =>
              [...(current ?? []), result.user].sort(
                (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || a.user_id.localeCompare(b.user_id),
              ),
            );
          }}
        />
      )}
      <TableCard
        title={t('users.title')}
        count={shown ? shown.length : null}
        actions={
          !adding && (
            <Button variant="primary" icon={UserPlus} onPress={() => setAdding(true)}>
              {t('users.add')}
            </Button>
          )
        }
        summary={<UserFilterBar filters={filters} onChange={changeFilters} />}
        columns={columns}
        rows={page.rows}
        getRowKey={(user) => user.user_id}
        caption={t('users.title')}
        onRowActivate={(user) => navigate(`/users/${encodeURIComponent(user.user_id)}`)}
        rowClassName={(user) => cx(!user.active && 'bg-surface-muted')}
        pageSize={PAGE_SIZE}
        rowHeight={4}
        fitRows
        offset={page.offset}
        total={page.total}
        onOffsetChange={page.setOffset}
        itemLabel={page.total === 1 ? t('users.item') : t('users.items')}
        status={status}
        statusAction={
          users.error ? (
            <Button icon={RotateCw} onPress={users.reload}>
              {t('Retry')}
            </Button>
          ) : (
            noMatch && <Button onPress={() => changeFilters(NO_USER_FILTERS)}>{t('Clear filters')}</Button>
          )
        }
        loading={!users.data && !users.error}
        loadingLabel={t('users.loading')}
      />
    </div>
  );
}


/** The accounts table while the session says who is signed in: its header over grey rows. */
function UsersPlaceholder() {
  const { t } = useI18n();
  const columns = useUserColumns();
  return (
    <div className="flex flex-col gap-5">
      <TableCard
        title={t('users.title')}
        summary={<UserFilterBar filters={NO_USER_FILTERS} onChange={noop} disabled />}
        columns={columns}
        rows={[]}
        getRowKey={String}
        pageSize={PAGE_SIZE}
        rowHeight={4}
        fitRows
        onOffsetChange={noop}
        loading
        loadingLabel={t('users.loading')}
      />
    </div>
  );
}


/**
 * Users (/users): every user account in one table, ten a page, for administrators; everyone else
 * reads that only administrators manage accounts. "Add user" sits at the top right of the table
 * and opens the form above it (`?add=1`, also what the + beside Users in the sidebar leads to),
 * the search and the role and status filters above its rows; a row opens the user's page.
 */
export function UsersPage() {
  const { t } = useI18n();
  const { me, can } = useSession();
  useDocumentTitle(t('nav.users'));
  if (!me) return <UsersPlaceholder />;
  if (!can('manage_users')) return <AdminOnlyNotice />;
  return <UserAdministration />;
}

