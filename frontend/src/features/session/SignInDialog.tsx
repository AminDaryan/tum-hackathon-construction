import { KeyRound, LogIn } from 'lucide-react';
import { useId, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { Button } from '../../components/Button.tsx';
import { TextField } from '../../components/Field.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { ApiError } from '../../services/apiClient.ts';
import { verifyAccessToken } from '../../services/sessionService.ts';
import { useI18n } from '../../i18n/useI18n.ts';
import { describeError } from '../../utils/errors.ts';

const NOTICES: Readonly<Record<string, string>> = {
  rejected: 'signIn.rejected',
  signed_out: 'signIn.signedOut',
};

interface SignInDialogProps {
  reason?: 'rejected' | 'signed_out' | null;
  onSignedIn: (token: string) => void;
}

/**
 * Sign-in for a server that requires an access token: a modal dialog (nothing else is rendered
 * while it is open) with one password field. The token is checked against a protected endpoint
 * before it is kept; it is never shown, logged or placed in an error message.
 */
export function SignInDialog({ reason = null, onSignedIn }: SignInDialogProps) {
  const { t } = useI18n();
  const headingId = useId();
  const descriptionId = useId();
  const inputRef = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const [token, setToken] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const verify = useAsyncAction((signal, candidate: string) => verifyAccessToken(candidate, { signal }).then(() => true));

  // In the commit that shows the dialog, not in an effect after it: otherwise the dialog is on
  // screen, and announced, for a moment with nothing focused.
  useLayoutEffect(() => {
    inputRef.current?.focus();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const candidate = token.trim();
    if (!candidate) {
      setProblem(t('signIn.missing'));
      inputRef.current?.focus();
      return;
    }
    setProblem(null);
    const accepted = await verify.execute(candidate);
    if (accepted) {
      onSignedIn(candidate);
    } else {
      inputRef.current?.focus();
    }
  };

  let error = problem;
  if (!error && verify.error) {
    error =
      verify.error instanceof ApiError && verify.error.code === 'unauthorized'
        ? t('signIn.notAccepted')
        : t('signIn.failed', { message: describeError(verify.error).message });
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-canvas px-4 py-8">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        aria-describedby={descriptionId}
        className="w-full max-w-md rounded-lg border border-hairline bg-surface p-6 shadow-overlay"
      >
        <div className="flex items-center gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent-subtle text-accent-strong">
            <KeyRound aria-hidden="true" className="size-5" strokeWidth={1.75} />
          </span>
          <h1 id={headingId} className="text-title text-ink">
            {t('signIn.title')}
          </h1>
        </div>
        <p id={descriptionId} className="mt-3 text-body text-ink-secondary">
          {t('signIn.description')}
        </p>
        {reason && NOTICES[reason] && (
          <p role="status" className="mt-3 rounded-md bg-context-bg px-3 py-2 text-callout text-ink">
            {t(NOTICES[reason])}
          </p>
        )}
        <form noValidate onSubmit={submit} className="mt-5 flex flex-col gap-4">
          <TextField
            label={t('signIn.label')}
            name="access-token"
            type="password"
            value={token}
            inputRef={inputRef}
            autoComplete="off"
            spellCheck="false"
            isDisabled={verify.pending}
            hint={t('signIn.help')}
            errorMessage={error ?? undefined}
            inputClassName="font-mono"
            onChange={(value) => {
              setToken(value);
              setProblem(null);
            }}
          />
          <Button type="submit" variant="primary" size="lg" icon={LogIn} loading={verify.pending} pendingLabel={t('signIn.checking')} className="w-full">
            {t('signIn.submit')}
          </Button>
        </form>
      </div>
    </div>
  );
}
