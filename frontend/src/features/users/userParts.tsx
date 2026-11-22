import { KeyRound, UserPlus } from 'lucide-react';
import { useId, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { Banner } from '../../components/Banner.tsx';
import { Button } from '../../components/Button.tsx';
import { CopyButton } from '../../components/CopyButton.tsx';
import { Section } from '../../components/Section.tsx';
import { Select } from '../../components/Select.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useI18n } from '../../i18n/useI18n.ts';
import type { IssuedToken as Issued, UserAccount } from '../../services/apiTypes.ts';
import { createUser } from '../../services/usersService.ts';
import { useSession } from '../../stores/useSession.ts';
import { cx } from '../../utils/classNames.ts';
import { describeError } from '../../utils/errors.ts';
import { displayName } from '../profile/ProfileParts.tsx';
import { ROLES } from '../profile/roles.ts';

const EMAIL = /^[^@\s]+@[^@\s]+$/;
const INPUT =
  'h-11 w-full rounded-md border bg-surface px-2.5 text-callout text-ink transition-colors hover:border-ink-tertiary disabled:opacity-50 pointer-coarse:h-12';

export function useRoleOptions() {
  const { t } = useI18n();
  return ROLES.map((role) => ({ value: role, label: t(`role.${role}`) }));
}

/** A new account: first and last name, optional email and role. The server answers with its first token. */
interface AddUserFormProps {
  onCreated: (issued: Issued) => void;
  onCancel: () => void;
}

export function AddUserForm({ onCreated, onCancel }: AddUserFormProps) {
  const { t } = useI18n();
  const roleOptions = useRoleOptions();
  const nameId = useId();
  const lastNameId = useId();
  const emailId = useId();
  const nameErrorId = useId();
  const emailErrorId = useId();
  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<UserAccount['role']>('reviewer');
  const [problems, setProblems] = useState<{ name?: string; email?: string }>({});
  const create = useAsyncAction((signal, body: Parameters<typeof createUser>[0]) => createUser(body, signal));

  useLayoutEffect(() => {
    nameRef.current?.focus();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const found: { name?: string; email?: string } = {};
    if (!name.trim()) found.name = t('users.nameMissing');
    if (email.trim() && !EMAIL.test(email.trim())) found.email = t('users.emailInvalid');
    setProblems(found);
    if (found.name) return nameRef.current?.focus();
    if (found.email) return emailRef.current?.focus();
    const issued = await create.execute({ first_name: name.trim(), last_name: lastName.trim(), email: email.trim(), role });
    if (issued) onCreated(issued);
    return undefined;
  };

  return (
    <form
      noValidate
      onSubmit={submit}
      aria-label={t('users.addTitle')}
      className="mb-5 grid gap-4 rounded-lg border border-hairline bg-surface-muted p-4 md:grid-cols-2 xl:grid-cols-[1fr_1fr_1.3fr_0.8fr_auto] xl:items-start"
    >
      <div className="flex min-w-0 flex-col gap-1">
        <label htmlFor={nameId} className="text-caption font-medium text-ink-secondary">
          {t('profile.firstName')}
        </label>
        <input
          ref={nameRef}
          id={nameId}
          value={name}
          maxLength={80}
          autoComplete="off"
          aria-invalid={problems.name ? true : undefined}
          aria-describedby={problems.name ? nameErrorId : undefined}
          onChange={(event) => setName(event.target.value)}
          className={cx(INPUT, problems.name ? 'border-danger' : 'border-control-border')}
        />
        {problems.name && (
          <p id={nameErrorId} className="text-caption text-danger">
            {problems.name}
          </p>
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        <label htmlFor={lastNameId} className="text-caption font-medium text-ink-secondary">
          {t('profile.lastName')}
        </label>
        <input
          id={lastNameId}
          value={lastName}
          maxLength={80}
          autoComplete="off"
          onChange={(event) => setLastName(event.target.value)}
          className={cx(INPUT, 'border-control-border')}
        />
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        <label htmlFor={emailId} className="text-caption font-medium text-ink-secondary">
          {t('users.email')}
        </label>
        <input
          ref={emailRef}
          id={emailId}
          type="email"
          value={email}
          maxLength={254}
          autoComplete="off"
          aria-invalid={problems.email ? true : undefined}
          aria-describedby={problems.email ? emailErrorId : undefined}
          onChange={(event) => setEmail(event.target.value)}
          className={cx(INPUT, problems.email ? 'border-danger' : 'border-control-border')}
        />
        {problems.email && (
          <p id={emailErrorId} className="text-caption text-danger">
            {problems.email}
          </p>
        )}
      </div>
      <Select label={t('users.role')} value={role} options={roleOptions}
        // The select offers only ROLES.
        onChange={(value) => setRole(value as UserAccount['role'])}
      />
      <div className="flex gap-2 xl:pt-5">
        <Button type="submit" variant="primary" icon={UserPlus} loading={create.pending}>
          {t('users.create')}
        </Button>
        <Button variant="ghost" onPress={onCancel}>
          {t('users.cancel')}
        </Button>
      </div>
      {create.error && (
        <p role="alert" className="text-callout text-danger md:col-span-2 xl:col-span-5">
          {describeError(create.error).message}
        </p>
      )}
    </form>
  );
}


/** A token that was just issued: shown once, with a copy button. */
interface IssuedTokenProps {
  issued: Issued;
  onDismiss: () => void;
}

export function IssuedToken({ issued, onDismiss }: IssuedTokenProps) {
  const { t } = useI18n();
  const headingId = useId();
  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    ref.current?.focus();
  }, [issued.token]);
  return (
    <section
      ref={ref}
      tabIndex={-1}
      aria-labelledby={headingId}
      className="mb-5 rounded-lg border border-accent/30 bg-accent-subtle p-4 outline-none"
    >
      <div className="flex items-start gap-3">
        <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-surface text-accent-strong">
          <KeyRound aria-hidden="true" className="size-4" strokeWidth={1.75} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 id={headingId} className="text-headline text-ink">
            {t('users.tokenTitle', { name: issued.user.name })}
          </h3>
          <p className="mt-1 text-callout text-ink-secondary">{t('users.tokenBody', { name: issued.user.name })}</p>
          <p
            data-testid="issued-token"
            className="mt-3 select-all break-all rounded-md border border-hairline bg-surface px-3 py-2 font-mono text-callout text-ink"
          >
            {issued.token}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <CopyButton text={issued.token} label={t('users.copyToken')} variant="secondary" />
            <Button variant="ghost" onPress={onDismiss}>
              {t('users.dismissToken')}
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}


/** Shown to everyone but administrators in place of the accounts. */
export function AdminOnlyNotice() {
  const { t } = useI18n();
  const { me } = useSession();
  return (
    <Section padded>
      <Banner tone="info" title={t('users.adminOnly')}>
        {t('users.adminOnlyHint', { name: displayName(me, t), role: me ? t(`role.${me.role}`) : '' })}
      </Banner>
    </Section>
  );
}

