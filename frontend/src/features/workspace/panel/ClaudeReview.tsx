import { Sparkles } from 'lucide-react';
import { Button } from '../../../components/Button.tsx';
import { t } from '../../../i18n/messages.ts';
import { useSession } from '../../../stores/useSession.ts';
import { describeError } from '../../../utils/errors.ts';
import { useStartValidationRun } from '../../validation/useStartValidationRun.ts';
import type { ValidationRunDetail } from '../../../services/apiTypes.ts';

/** The check that lists what Claude found (backend/app/validation/semantic/bill_review.py). */
const BILL_REVIEW_CHECK = 'llm.bill_review';

/** Why the finished run holds no Claude review, or null when it does. */
function notReviewed(run: ValidationRunDetail | undefined): string | null {
  const report = run?.detector_reports?.find((entry) => entry.detector_id === BILL_REVIEW_CHECK);
  if (!report || report.status === 'completed') return null;
  return report.skipped_reasons?.[0] ?? report.error ?? '';
}

interface ClaudeReviewProps {
  datasetId: string;
  /** `health.bill_review_available` */
  available: boolean;
  onCompleted: (run: ValidationRunDetail) => void;
}

/**
 * Sends the bill to Claude for review and validates it (a run with `bill_review`), for a person
 * who may write, on a server that can (an Anthropic key); nothing is shown otherwise. Claude's
 * claims join the run's findings as suspicions (check `llm.bill_review`). When the review did
 * not start or got no answer, it says why.
 */
export function ClaudeReview({ datasetId, available, onCompleted }: ClaudeReviewProps) {
  const { can } = useSession();
  const review = useStartValidationRun(datasetId, { onCompleted, billReview: true });
  if (!available || !can('write')) return null;
  const problem = review.error ? describeError(review.error).message : notReviewed(review.result);
  return (
    <div className="space-y-1">
      <Button icon={Sparkles} loading={review.pending} pendingLabel={t('Claude is reviewing the bill…')} onPress={() => review.execute()}>
        {t('Send the bill to Claude for review')}
      </Button>
      {problem !== null && (
        <p role="alert" className="text-callout text-danger">
          {t('The bill was not reviewed.')} {problem}
        </p>
      )}
    </div>
  );
}
