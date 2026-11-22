import { KeyRound, Pencil, Trash2, UserCheck, UserX } from 'lucide-react';
import { useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { usePageTitle } from '../../app/pageTitle.tsx';
import { refreshSidebarLists } from '../../app/sidebarLists.ts';
import { Badge } from '../../components/Badge.tsx';
import { Banner } from '../../components/Banner.tsx';
import { Button } from '../../components/Button.tsx';
import { Dialog } from '../../components/Dialog.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { KeyValueList } from '../../components/KeyValueList.tsx';
import { Select } from '../../components/Select.tsx';
import { Timestamp } from '../../components/Timestamp.tsx';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { useI18n } from '../../i18n/useI18n.ts';
import type { IssuedToken as Issued, UserAccount as Account } from '../../services/apiTypes.ts';
import { deleteUser, issueUserToken, listUsers, updateUser } from '../../services/usersService.ts';
import { useSession } from '../../stores/useSession.ts';
import { cx } from '../../utils/classNames.ts';
import { describeError } from '../../utils/errors.ts';
import { Avatar } from '../profile/Avatar.tsx';
import { ProfileDetailsForm } from '../profile/ProfileDetailsForm.tsx';
import { RoleBadge } from '../profile/ProfileParts.tsx';
import { AdminOnlyNotice, IssuedToken, useRoleOptions } from './userParts.tsx';
import { UserPlaceholder } from './UserPlaceholder.tsx';

/** One account, for administrators: its details, and the changes an administrator makes to it. */
type UserChanges = Parameters<typeof updateUser>[1];

function UserAccount({ userId }: { userId: string | undefined }) {
  const { t } = useI18n();
  const { me, reloadMe } = useSession();
  const navigate = useNavigate();
  const roleOptions = useRoleOptions();
  const users = useApiResource((signal) => listUsers(signal), []);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState(false);
  const user = users.data?.find((candidate) => candidate.user_id === userId) ?? null;
  usePageTitle({ title: user?.name, pending: !user, back: { label: t('users.back'), to: '/users' } });

  if (users.error && !users.data) return <ErrorState error={users.error} title={t('users.loadFailed')} onRetry={users.reload} />;
  if (!users.data) return <UserPlaceholder label={t('users.loading')} />;
  // An account that is gone (deleted, or a mistyped address): back to the table.
  if (!user) return <Navigate to="/users" replace />;

  const self = user.user_id === me?.user_id;
  const run = async <T,>(action: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setFailure(null);
    try {
      return await action();
    } catch (error) {
      setFailure(error);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  const replace = (changed: Account) =>
    users.setData((current) => (current ?? []).map((candidate) => (candidate.user_id === changed.user_id ? changed : candidate)));
  const change = (changes: UserChanges) =>
    run(async () => {
      replace(await updateUser(user.user_id, changes));
      refreshSidebarLists();
      if (self) reloadMe();
    });
  const issue = () =>
    run(async () => {
      const result = await issueUserToken(user.user_id);
      replace(result.user);
      setIssued(result);
    });
  const remove = () =>
    run(async () => {
      await deleteUser(user.user_id);
      refreshSidebarLists();
      navigate('/users');
    });

  // The details the Edit form changes; while it is open it shows them instead of this list.
  const profileDetails = [
    { label: t('profile.firstName'), value: user.first_name || null },
    { label: t('profile.lastName'), value: user.last_name || null },
    { label: t('profile.email'), value: user.email || null },
    { label: t('profile.jobTitle'), value: user.job_title || null },
    { label: t('profile.phone'), value: user.phone || null },
  ];
  const accountDetails = [
    {
      label: t('profile.status'),
      value: <Badge tone={user.active ? 'accent' : 'neutral'}>{t(user.active ? 'users.active' : 'users.inactive')}</Badge>,
    },
    { label: t('profile.memberSince'), value: user.created_at ? <Timestamp value={user.created_at} /> : null },
    {
      label: t('profile.token'),
      value: user.token_hint ? (
        <>
          <span className="font-mono text-callout">{t('users.tokenEnding', { hint: user.token_hint })}</span>
          <span className="text-ink-secondary">
            {', '}
            {t('profile.tokenIssued')} <Timestamp value={user.token_issued_at} />
          </span>
        </>
      ) : (
        t('users.noToken')
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-5">
      {issued && <IssuedToken issued={issued} onDismiss={() => setIssued(null)} />}
      {failure != null && (
        <Banner tone="danger" title={t('users.actionFailed')}>
          {describeError(failure).message}
        </Banner>
      )}
      <section aria-label={user.name} className="rounded-lg border border-hairline bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-b border-hairline p-4">
          <div className="flex min-w-0 items-center gap-4">
            <Avatar name={user.name} role={user.role} size="lg" className={cx(!user.active && 'opacity-50')} />
            <div className="min-w-0">
              <p className="flex items-center gap-2 truncate text-headline text-ink">
                {user.name}
                {self && <Badge tone="accent">{t('users.you')}</Badge>}
              </p>
              <div className="mt-1.5">
                <RoleBadge role={user.role} />
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1">
            <Button variant="ghost" icon={Pencil} isDisabled={busy || editing} onPress={() => setEditing(true)}>
              {t('users.edit')}
            </Button>
            <Button variant="ghost" icon={KeyRound} isDisabled={busy} onPress={issue}>
              {t('users.newToken')}
            </Button>
            {!self && (
              <Button variant="ghost" icon={user.active ? UserX : UserCheck} isDisabled={busy} onPress={() => change({ active: !user.active })}>
                {t(user.active ? 'users.deactivate' : 'users.activate')}
              </Button>
            )}
            {!self && (
              <Button variant="ghost" icon={Trash2} isDisabled={busy} onPress={() => setConfirming(true)}>
                {t('users.delete')}
              </Button>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-5 p-4">
          <Select
            label={t('users.role')}
            value={user.role}
            options={roleOptions}
            disabled={self || busy}
            // The select offers only ROLES.
            onChange={(role) => change({ role: role as Account['role'] })}
            className="w-56 max-w-full"
          />
          {editing && (
            <ProfileDetailsForm
              account={user}
              save={(changes, signal) => updateUser(user.user_id, changes, signal)}
              onSaved={(changed) => {
                replace(changed);
                if (self) reloadMe();
                setEditing(false);
              }}
              onCancel={() => setEditing(false)}
            />
          )}
          <KeyValueList items={editing ? accountDetails : [...profileDetails, ...accountDetails]} />
        </div>
      </section>
      <Dialog open={confirming} onOpenChange={setConfirming} role="alertdialog" title={t('users.deleteFor', { name: user.name })} size="sm">
        <div className="flex flex-col gap-4">
          <p className="text-callout text-ink">{t('users.confirmDelete', { name: user.name })}</p>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onPress={() => setConfirming(false)}>
              {t('users.cancel')}
            </Button>
            <Button variant="primary" icon={Trash2} loading={busy} onPress={remove}>
              {t('users.confirmDeleteYes')}
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

/**
 * One user (/users/:userId), opened from the Users table: the account's details (name, email,
 * job title, phone, status, since when, token) and, for an administrator, editing those details,
 * its role, a new access token, deactivating and deleting it. Nobody demotes, deactivates or deletes their own account.
 */
export function UserPage() {
  const { t } = useI18n();
  const { userId } = useParams();
  const { me, can } = useSession();
  useDocumentTitle(t('nav.users'));
  if (!me) return <UserPlaceholder label={t('users.loading')} />;
  if (!can('manage_users')) return <AdminOnlyNotice />;
  return <UserAccount key={userId} userId={userId} />;
}

