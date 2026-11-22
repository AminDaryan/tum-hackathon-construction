import { Check, LogIn, Minus } from 'lucide-react';
import { useId, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { Badge } from '../../components/Badge.tsx';
import { Button } from '../../components/Button.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useI18n } from '../../i18n/useI18n.ts';
import { ApiError } from '../../services/apiClient.ts';
import { getMe } from '../../services/usersService.ts';
import { cx } from '../../utils/classNames.ts';
import { describeError } from '../../utils/errors.ts';
import { PERMISSIONS, ROLE_STYLE } from './roles.ts';
import type { Me } from '../../services/apiTypes.ts';

/** The name to show: the local and configured administrators are named in the interface language. */
export function displayName(me: Me | null | undefined, t: (key: string) => string): string {
  if (!me) return '';
  if (me.kind === 'local') return t('profile.localUser');
  if (me.kind === 'service') return t('profile.serviceUser');
  return me.name;
}

interface RoleBadgeProps {
  role: string;
}

/** The role as a badge with its icon. */
export function RoleBadge({ role }: RoleBadgeProps) {
  const { t } = useI18n();
  const style = ROLE_STYLE[role] ?? ROLE_STYLE.viewer;
  return (
    <Badge tone={style.tone} icon={style.icon}>
      {t(`role.${role}`)}
    </Badge>
  );
}

interface PermissionListProps {
  permissions: string[];
}

/** The three permissions, each allowed or not for the role. */
export function PermissionList({ permissions }: PermissionListProps) {
  const { t } = useI18n();
  return (
    <ul className="flex flex-col gap-1.5">
      {PERMISSIONS.map((permission) => {
        const allowed = permissions.includes(permission);
        const Icon = allowed ? Check : Minus;
        return (
          <li key={permission} className={cx('flex items-center gap-2 text-callout', allowed ? 'text-ink' : 'text-ink-tertiary')}>
            <span
              className={cx(
                'inline-flex size-5 shrink-0 items-center justify-center rounded-full',
                allowed ? 'bg-accent-subtle text-accent-strong' : 'bg-surface-muted text-ink-tertiary',
              )}
            >
              <Icon aria-hidden="true" className="size-3" strokeWidth={2.5} />
            </span>
            <span>
              {t(`permission.${permission}`)}
              <span className="sr-only">: {t(allowed ? 'profile.allowed' : 'profile.notAllowed')}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

interface TokenFormProps {
  onSignedIn: (token: string) => void;
  onCancel?: () => void;
}

/**
 * Signs in with a personal access token without leaving the page. The token is checked with
 * GET /me first; one that names nobody (the server then acts as the local administrator) is
 * refused, so a mistyped token never looks like a successful sign-in.
 */
export function TokenForm({ onSignedIn, onCancel }: TokenFormProps) {
  const { t } = useI18n();
  const inputId = useId();
  const helpId = useId();
  const errorId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [token, setToken] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const verify = useAsyncAction((signal, candidate: string) => getMe({ signal, authToken: candidate }));

  useLayoutEffect(() => {
    inputRef.current?.focus();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const candidate = token.trim();
    if (!candidate) {
      setProblem(t('profile.tokenMissing'));
      inputRef.current?.focus();
      return;
    }
    setProblem(null);
    const me = await verify.execute(candidate);
    if (!me) {
      inputRef.current?.focus();
      return;
    }
    if (me.kind === 'local') {
      setProblem(t('profile.tokenNotUser'));
      inputRef.current?.focus();
      return;
    }
    onSignedIn(candidate);
  };

  let error = problem;
  if (!error && verify.error) {
    error =
      verify.error instanceof ApiError && verify.error.code === 'unauthorized'
        ? t('profile.tokenRejected')
        : t('profile.tokenFailed', { message: describeError(verify.error).message });
  }

  return (
    <form noValidate onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor={inputId} className="text-caption font-medium text-ink-secondary">
        {t('profile.tokenLabel')}
      </label>
      <input
        ref={inputRef}
        id={inputId}
        name="user-access-token"
        type="password"
        value={token}
        autoComplete="off"
        spellCheck={false}
        disabled={verify.pending}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${helpId} ${errorId}` : helpId}
        onChange={(event) => {
          setToken(event.target.value);
          setProblem(null);
        }}
        className={cx(
          'h-11 w-full rounded-md border bg-surface px-2.5 font-mono text-callout text-ink transition-colors hover:border-ink-tertiary disabled:opacity-50 pointer-coarse:h-12',
          error ? 'border-danger' : 'border-control-border',
        )}
      />
      <p id={helpId} className="text-caption text-ink-tertiary">
        {t('profile.tokenHelp')}
      </p>
      {error && (
        <p id={errorId} role="alert" className="text-caption text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" icon={LogIn} loading={verify.pending}>
          {t('profile.tokenSubmit')}
        </Button>
        {onCancel && (
          <Button variant="ghost" onPress={onCancel}>
            {t('profile.tokenCancel')}
          </Button>
        )}
      </div>
    </form>
  );
}
