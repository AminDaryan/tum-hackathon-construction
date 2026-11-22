import { CircleAlert, RotateCw } from 'lucide-react';
import { cx } from '../utils/classNames.ts';
import { describeError } from '../utils/errors.ts';
import { focusSectionHeading } from '../utils/focus.ts';
import { Button } from './Button.tsx';
import { t } from '../i18n/messages.ts';

interface ErrorStateProps {
  error: Error | Record<string, unknown>;
  title?: string;
  onRetry?: () => void;
  compact?: boolean;
  problems?: string[];
}

/**
 * A failed request: what went wrong, the backend error code and request id (for support), and
 * a Retry action when the caller can repeat the request. The problems listed are the error's
 * `details.errors`, unless the caller passes `problems`: its own wording of them (for example
 * named by the check a plan step concerns).
 */
export function ErrorState({ error, title, onRetry, compact = false, problems: ownProblems }: ErrorStateProps) {
  const { message, hint, problems: errorProblems, code, requestId } = describeError(error);
  const problems = ownProblems ?? errorProblems;
  return (
    <div role="alert" className={cx('flex items-start gap-3 rounded-md bg-danger-bg text-left', compact ? 'p-3' : 'p-4')}>
      <CircleAlert aria-hidden="true" className="mt-px size-5 shrink-0 text-danger" strokeWidth={1.75} />
      <div className="min-w-0 flex-1">
        <p className="text-headline text-ink">{title ?? t('Something went wrong')}</p>
        <p className="mt-1 break-words text-body text-ink-secondary">{message}</p>
        {problems.length > 0 && (
          <ul className="mt-1 list-disc break-words pl-5 text-callout text-ink-secondary">
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        )}
        {hint && <p className="mt-1 text-callout text-ink">{hint}</p>}
        {(code || requestId) && (
          <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-caption text-ink-secondary">
            {code && (
              <div className="flex gap-1.5">
                <dt>{t('Code')}</dt>
                <dd className="font-mono text-ink">{code}</dd>
              </div>
            )}
            {requestId && (
              <div className="flex gap-1.5">
                <dt>{t('Request ID')}</dt>
                <dd className="select-all break-all font-mono text-ink">{requestId}</dd>
              </div>
            )}
          </dl>
        )}
        {onRetry && (
          <Button
            className="mt-3"
            icon={RotateCw}
            onPress={(event) => {
              focusSectionHeading(event.target);
              onRetry();
            }}
          >
            {t('Retry')}
          </Button>
        )}
      </div>
    </div>
  );
}
