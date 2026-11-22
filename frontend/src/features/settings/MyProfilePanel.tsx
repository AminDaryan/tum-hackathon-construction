import type { ReactNode } from 'react';
import { Badge } from '../../components/Badge.tsx';
import { KeyValueList } from '../../components/KeyValueList.tsx';
import { Skeleton, SkeletonText } from '../../components/Skeleton.tsx';
import { Section } from '../../components/Section.tsx';
import { Timestamp } from '../../components/Timestamp.tsx';
import { useI18n } from '../../i18n/useI18n.ts';
import { updateMe } from '../../services/usersService.ts';
import { useSession } from '../../stores/useSession.ts';
import { Avatar } from '../profile/Avatar.tsx';
import { PermissionList, RoleBadge, TokenForm, displayName } from '../profile/ProfileParts.tsx';
import { ProfileDetailsForm } from '../profile/ProfileDetailsForm.tsx';
import type { UserAccount } from '../../services/apiTypes.ts';

interface ProfileHeaderProps {
  me: { role: string };
  name: string;
  subtitle?: string;
}

/** The header of the profile: avatar, name, job title, email and role. */
function ProfileHeader({ me, name, subtitle }: ProfileHeaderProps) {
  const { t } = useI18n();
  return (
    <div className="flex min-w-0 items-center gap-4">
      <Avatar name={name} role={me.role} size="lg" />
      <div className="min-w-0">
        <p className="truncate text-headline text-ink">{name}</p>
        {subtitle && <p className="truncate text-callout text-ink-secondary">{subtitle}</p>}
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <span className="sr-only">{t('profile.role')}: </span>
          <RoleBadge role={me.role} />
        </div>
      </div>
    </div>
  );
}

interface RoleAndAccessProps {
  me: { role: string; permissions?: string[] };
  account: UserAccount | null;
}

/** Role, what it allows, and the account's facts that only an administrator changes. */
function RoleAndAccess({ me, account }: RoleAndAccessProps) {
  const { t } = useI18n();
  const items: { label: string; value: ReactNode }[] = [
    { label: t('profile.role'), value: <RoleBadge role={me.role} /> },
    { label: t('profile.roleMeans'), value: t(`role.${me.role}.description`) },
  ];
  if (account) {
    items.push(
      {
        label: t('profile.status'),
        value: <Badge tone={account.active ? 'accent' : 'neutral'}>{t(account.active ? 'users.active' : 'users.inactive')}</Badge>,
      },
      { label: t('profile.memberSince'), value: <Timestamp value={account.created_at} /> },
      {
        label: t('profile.token'),
        value: account.token_hint ? (
          <>
            <span className="font-mono">{t('users.tokenEnding', { hint: account.token_hint })}</span>
            <span className="text-ink-secondary">
              {', '}
              {t('profile.tokenIssued')} <Timestamp value={account.token_issued_at} />
            </span>
          </>
        ) : (
          t('users.noToken')
        ),
      },
    );
  }
  return (
    // An administrator changes roles themselves, so the note that only one can is not for them.
    <Section title={t('profile.access.title')} description={me.role === 'admin' ? undefined : t('profile.access.description')} padded>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <KeyValueList items={items} />
        <div>
          <h3 className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">{t('profile.can')}</h3>
          <PermissionList permissions={me.permissions ?? []} />
        </div>
      </div>
    </Section>
  );
}

/**
 * The Profile overlay, opened from the user menu, under its own title. A user account sees and edits its details (first and last name, email,
 * job title, phone) and sees its role, status, membership and token. The local administrator and
 * a configured token have no profile: they see their role and can sign in with a personal token.
 */
export function MyProfilePanel() {
  const { t } = useI18n();
  const { me, signIn, reloadMe } = useSession();
  if (!me) {
    // Who is signed in is still loading: the profile's header as grey shapes, in its own box.
    return (
      <Section padded>
        <p role="status" className="sr-only">
          {t('profile.loading')}
        </p>
        <div aria-hidden="true" className="flex flex-col gap-4">
          <div className="flex items-center gap-4">
            <Skeleton className="size-12 shrink-0 rounded-full" />
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-5 w-28 rounded-full" />
            </div>
          </div>
          <SkeletonText lines={2} className="max-w-2xl" />
        </div>
      </Section>
    );
  }
  const account = me.kind === 'user' ? me.account : null;
  const name = displayName(me, t);
  if (!account) {
    return (
      <>
        <Section padded>
          <ProfileHeader me={me} name={name} />
          <div className="mt-5 max-w-md border-t border-hairline pt-5">
            <h3 className="text-headline text-ink">{t('profile.noAccount.title')}</h3>
            <p className="mb-3 mt-1 text-callout text-ink-secondary">{t('profile.noAccount.body')}</p>
            <TokenForm onSignedIn={signIn} />
          </div>
        </Section>
        <RoleAndAccess me={me} account={null} />
      </>
    );
  }
  const subtitle = [account.job_title, account.email].filter(Boolean).join(', ');
  return (
    <>
      <Section padded>
        <ProfileHeader me={me} name={name} subtitle={subtitle} />
      </Section>
      <Section title={t('profile.details.title')} description={t('profile.details.description')} padded>
        <ProfileDetailsForm account={account} save={updateMe} onSaved={reloadMe} />
      </Section>
      <RoleAndAccess me={me} account={account} />
    </>
  );
}
