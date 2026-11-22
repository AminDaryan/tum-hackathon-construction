import { useLayoutEffect, useRef, useState } from 'react';
import { useAsyncAction, type AsyncAction } from '../../hooks/useAsyncAction.ts';
import { startValidationRun } from '../../services/validationService.ts';
import { isTerminalRunStatus, pollValidationRun } from './pollValidationRun.ts';
import type { ValidationRunDetail } from '../../services/apiTypes.ts';

/**
 * Starts a validation run for a dataset (POST /datasets/{id}/validation-runs) and tracks it
 * until it has finished. `execute()` starts the run; the server runs every registered check.
 *
 * The request asks for a background run (`Prefer: respond-async`). On 202 the run is followed by
 * polling GET /validation-runs/{run_id} (see pollValidationRun), and `trackedRun` holds its
 * latest snapshot (`queued`, `running`) for the live status. On 201 the server has already
 * finished the run. Either way `pending` lasts until the run has finished, and unmounting stops
 * the request and the polling. When following the run fails, `trackedRun` keeps the last
 * snapshot so the page can link to the run.
 *
 * @param options `onAccepted` is called once the server has accepted the run (202) or finished it
 *   (201); `onCompleted` with the finished run, e.g. to refresh summaries and issue counts;
 *   `matchMaterials` asks the local model for material matches first, `billReview` Claude for
 *   a review of the bill (see startValidationRun)
 * @returns `execute()` starts the run; `result` is the finished run
 */
export function useStartValidationRun(
  datasetId: string,
  {
    onAccepted,
    onCompleted,
    matchMaterials = false,
    billReview = false,
  }: {
    onAccepted?: (run: ValidationRunDetail) => void;
    onCompleted?: (run: ValidationRunDetail) => void;
    matchMaterials?: boolean;
    billReview?: boolean;
  } = {},
): AsyncAction<[], ValidationRunDetail> & { trackedRun: ValidationRunDetail | null } {
  const callbacksRef = useRef({ onAccepted, onCompleted });
  const [trackedRun, setTrackedRun] = useState<ValidationRunDetail | null>(null);
  useLayoutEffect(() => {
    callbacksRef.current = { onAccepted, onCompleted };
  });
  const action = useAsyncAction(async (signal) => {
    setTrackedRun(null);
    const { run } = await startValidationRun(datasetId, { signal, matchMaterials, billReview });
    callbacksRef.current.onAccepted?.(run);
    let finished = run;
    if (!isTerminalRunStatus(run.status)) {
      setTrackedRun(run);
      finished = await pollValidationRun(run.run_id, {
        signal,
        onUpdate: (snapshot) => {
          if (!signal.aborted) setTrackedRun(snapshot);
        },
      });
      setTrackedRun(null);
    }
    callbacksRef.current.onCompleted?.(finished);
    return finished;
  });
  return { ...action, trackedRun };
}
