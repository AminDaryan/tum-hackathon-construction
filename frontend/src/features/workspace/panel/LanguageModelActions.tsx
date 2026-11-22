import { Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '../../../components/Button.tsx';
import { useAsyncAction } from '../../../hooks/useAsyncAction.ts';
import { t } from '../../../i18n/messages.ts';
import { getRiskDiscoveryRun, startRiskDiscovery } from '../../../services/validationService.ts';
import { useSession } from '../../../stores/useSession.ts';
import { describeError } from '../../../utils/errors.ts';
import { ClaudeReview } from './ClaudeReview.tsx';
import type { RiskReport, ValidationRunDetail } from '../../../services/apiTypes.ts';

const POLL_MS = 2000;
const RUNNING: ReadonlySet<string> = new Set(['queued', 'running']);

interface LanguageModelActionsProps {
  runId: string;
  datasetId: string;
  discovery?: RiskReport['discovery'] | null;
  /** `health.llm.ready` */
  localModelReady: boolean;
  /** `health.bill_review_available` */
  billReviewAvailable: boolean;
  onDiscovered: (discoveryRunId: string | null) => void;
  onMatchMaterials: () => void;
  matchingMaterials: boolean;
  /** the run the Claude review started has finished */
  onRunCompleted: (run: ValidationRunDetail) => void;
}

/**
 * What the language models can do for this run, at the end of the Risks tab. Once the local model
 * is ready: look for more risks (discovery runs once, and its stored result is applied when it
 * ends) and suggest the materials of priced positions and validate again, with the state of
 * discovery under the buttons. Then the Claude review, on a server that can send the bill to
 * Claude, for a person who may write. Nothing is shown when neither applies.
 */
export function LanguageModelActions({
  runId,
  datasetId,
  discovery,
  localModelReady,
  billReviewAvailable,
  onDiscovered,
  onMatchMaterials,
  matchingMaterials,
  onRunCompleted,
}: LanguageModelActionsProps) {
  const { can } = useSession();
  const [watching, setWatching] = useState<string | null>(null);
  const start = useAsyncAction((signal) => startRiskDiscovery(runId, {}, { signal }));

  useEffect(() => {
    if (!watching) return undefined;
    let cancelled = false;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const run = await getRiskDiscoveryRun(runId, watching, { signal: controller.signal });
        if (cancelled) return;
        if (RUNNING.has(run.status)) {
          setTimeout(poll, POLL_MS);
          return;
        }
        setWatching(null);
        onDiscovered(run.discovery_run_id);
      } catch {
        if (!cancelled) setWatching(null);
      }
    };
    poll();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [watching, runId, onDiscovered]);

  const begin = async () => {
    const outcome = await start.execute();
    if (outcome?.run?.discovery_run_id) setWatching(outcome.run.discovery_run_id);
  };

  const claudeOffered = billReviewAvailable && can('write');
  if (!localModelReady && !claudeOffered) return null;
  const failure = start.error ? describeError(start.error) : null;
  return (
    <section aria-label={t('Language model')} className="space-y-2 border-t border-hairline pt-3">
      {localModelReady && (
        <>
          <div className="flex flex-wrap gap-2">
            <Button icon={Sparkles} loading={start.pending || Boolean(watching)} pendingLabel={t('Looking for more risks…')} onPress={begin}>
              {t('Look for more risks with the local model')}
            </Button>
            <Button icon={Sparkles} loading={matchingMaterials} pendingLabel={t('Matching materials…')} onPress={() => onMatchMaterials()}>
              {t('Match materials with the local model and validate')}
            </Button>
          </div>
          {discovery?.detail && <p className="text-caption text-ink-tertiary">{discovery.detail}</p>}
          {failure && (
            <p role="alert" className="text-callout text-danger">
              {t('Discovery did not start.')} {failure.message}
            </p>
          )}
        </>
      )}
      {claudeOffered && <ClaudeReview datasetId={datasetId} available={billReviewAvailable} onCompleted={onRunCompleted} />}
    </section>
  );
}
