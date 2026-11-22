import { Info } from 'lucide-react';
import { useState } from 'react';
import { IconButton } from '../../components/IconButton.tsx';
import { Button } from '../../components/Button.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { StatusBadge } from '../../components/StatusBadge.tsx';
import { Timestamp } from '../../components/Timestamp.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { t, tRich } from '../../i18n/messages.ts';
import { finishValidationRunReview, reopenValidationRunReview } from '../../services/validationService.ts';
import { pluralize } from '../../utils/format.ts';
import type { ValidationRunDetail } from '../../services/apiTypes.ts';

const UNFINISHED = new Set(['queued', 'running']);

interface RunReviewControlsProps {
  run: ValidationRunDetail;
  onUpdated?: (run: ValidationRunDetail) => void;
}

/**
 * Finishes or reopens a run review. Finishing is allowed only after the run has finished and no
 * finding is pending review.
 */
export function RunReviewControls({ run, onUpdated = () => {} }: RunReviewControlsProps) {
  const pendingReview = run.issue_counts?.by_review_status?.pending_review;
  const isFinished = run.review_status === 'finished';
  const disabledReason =
    isFinished
      ? null
      : UNFINISHED.has(run.status)
        ? t('The review can be finished only after the validation run completed.')
        : pendingReview > 0
          ? t('{findings} still pending review.', { findings: pluralize(pendingReview, 'finding') })
          : null;
  const [announcement, setAnnouncement] = useState('');
  const action = useAsyncAction((signal) =>
    isFinished
      ? reopenValidationRunReview(run.run_id, { signal })
      : finishValidationRunReview(run.run_id, { signal }),
  );

  const toggle = async () => {
    setAnnouncement('');
    const updated = await action.execute();
    if (updated) {
      setAnnouncement(
        updated.review_status === 'finished'
          ? t('Run review marked as finished.')
          : t('Run review reopened.'),
      );
      onUpdated(updated);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-callout text-ink-secondary">
        <StatusBadge kind="run_review" status={run.review_status} />
        {run.review_finished_at && (
          <span className="text-caption text-ink-tertiary">
            {tRich('since {time}', { time: <Timestamp value={run.review_finished_at} /> })}
          </span>
        )}
        {typeof pendingReview === 'number' && (
          <span className="inline-flex items-center gap-1 text-caption text-ink-tertiary">
            {t('{findings} pending review', { findings: pluralize(pendingReview, 'finding') })}
            <IconButton icon={Info} label={t('Unreviewed findings in the selected validation run of this file. Counts all reviewers, regardless of risk list filters.')} />
          </span>
        )}
      </div>
      <Button
        variant={isFinished ? 'secondary' : 'primary'}
        loading={action.pending}
        isDisabled={!isFinished && Boolean(disabledReason)}
        onPress={toggle}
      >
        {isFinished ? t('Reopen review') : t('Finish review')}
      </Button>
      {disabledReason && !pendingReview && (
        <p className="text-callout text-ink-secondary">{disabledReason}</p>
      )}
      {action.error && !action.pending && (
        <ErrorState error={action.error} title={t('The run review status was not updated')} compact />
      )}
      <p role="status" className="text-callout text-success">
        {announcement}
      </p>
    </div>
  );
}
