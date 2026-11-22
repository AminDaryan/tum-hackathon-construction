import { ErrorState } from '../../components/ErrorState.tsx';
import { StatusBadge } from '../../components/StatusBadge.tsx';
import { t } from '../../i18n/messages.ts';
import { cx } from '../../utils/classNames.ts';
import { formatCount, pluralize } from '../../utils/format.ts';
import { countDetectorStatuses } from './detectorCounts.ts';
import type { ValidationRunDetail } from '../../services/apiTypes.ts';

function outcomeText(run: ValidationRunDetail) {
  if (run.status === 'failed') {
    return t('The validation run failed before detectors could finish. See the run details for warnings.');
  }
  const counts = countDetectorStatuses(run.detector_reports);
  const values = {
    issues: pluralize(run.issue_count ?? 0, 'issue'),
    detectors: pluralize(counts.completed, 'detector'),
    skipped: formatCount(counts.skipped),
    failed: formatCount(counts.failed),
    stopped: formatCount(counts.stopped),
  };
  return counts.stopped > 0
    ? t('Validation run finished with {issues}. {detectors} completed, {skipped} skipped, {failed} failed, {stopped} stopped.', values)
    : t('Validation run finished with {issues}. {detectors} completed, {skipped} skipped, {failed} failed.', values);
}

function progressText(run: ValidationRunDetail) {
  return run.status === 'queued'
    ? t('Validation run queued. It starts when the server is ready; this page updates when it has finished.')
    : t('Validation run in progress on the server. This page updates when it has finished.');
}

interface RunValidationStatusProps {
  pending: boolean;
  error?: Error | null;
  result?: ValidationRunDetail | null;
  trackedRun?: ValidationRunDetail | null;
}

/**
 * Progress and outcome of a validation run started on this page, for screen readers: the
 * sentence is an aria-live region that stays mounted (and hidden), so "queued", "running" and the
 * outcome are announced; the Validate button shows the progress and a finished run opens the Risks
 * tab. Shown on screen only when something went wrong: a failed run, or an error starting or
 * following it. `trackedRun` is the latest snapshot of a run the server runs in the background.
 */
export function RunValidationStatus({ pending, error, result, trackedRun = null }: RunValidationStatusProps) {
  let message = '';
  if (pending && trackedRun) {
    message = progressText(trackedRun);
  } else if (pending) {
    message = t('Running validation. Detectors run on the server; this page updates when the run has finished.');
  } else if (result) {
    message = outcomeText(result);
  }
  const failedRun = !pending && result?.status === 'failed';
  const showError = Boolean(error) && !pending;
  // Without a failure the wrappers take no room (`contents`) and only the hidden live region stays
  // mounted, so the space around this status comes from its container.
  return (
    <div className={cx(failedRun || showError ? 'flex flex-col gap-3' : 'contents')}>
      <div
        className={cx(
          failedRun ? 'flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-hairline bg-surface px-4 py-3' : 'contents',
        )}
      >
        {failedRun && <StatusBadge kind="run" status={result.status} />}
        <p role="status" className={cx('min-w-0 flex-1 text-callout text-ink', !failedRun && 'sr-only')}>
          {message}
        </p>
      </div>
      {showError && (
        <div className="flex flex-col items-start gap-2">
          <ErrorState
            error={error!}
            title={trackedRun ? t('The progress of the validation run could not be followed') : t('The validation run could not be completed')}
            compact
          />
        </div>
      )}
    </div>
  );
}
