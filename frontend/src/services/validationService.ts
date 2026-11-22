/**
 * Validation runs (docs/api/rest-api.md#validation-runs).
 */
import { apiClient, apiPath, requestJsonResponse } from "./apiClient.ts";
import type {
  DiscoveryRun,
  RiskReport,
  RiskReview,
  ValidationRunDetail,
  ValidationRunSummary,
} from "./apiTypes.ts";

/**
 * Starts a validation run. The backend runs every registered check; a client cannot choose them.
 *
 * The request carries `Prefer: respond-async` (RFC 7240). A backend with background runs answers
 * 202 Accepted with the run in status `queued` or `running` (and a `Location` header naming it);
 * the caller then polls {@link getValidationRun}. A backend without them ignores the preference
 * and answers 201 with the finished run.
 *
 * @param options `matchMaterials` first asks the local model to suggest price-reference
 *   materials for the rows the keywords cannot match (stored; later runs reuse the answers
 *   without asking); `billReview` first sends the bill to Claude for review (only on a server
 *   whose health says `bill_review_available`; stored the same way)
 * @returns `accepted` is true for 202 (the run continues in the background)
 */
export async function startValidationRun(
  datasetId: string,
  {
    signal,
    matchMaterials = false,
    billReview = false,
  }: { signal?: AbortSignal; matchMaterials?: boolean; billReview?: boolean } = {},
): Promise<{ run: ValidationRunDetail; accepted: boolean }> {
  const { data, status } = await requestJsonResponse<ValidationRunDetail>(
    apiPath`/datasets/${datasetId}/validation-runs`,
    {
      method: "POST",
      json: { ...(matchMaterials && { match_materials: true }), ...(billReview && { bill_review: true }) },
      headers: { Prefer: "respond-async" },
      signal,
    },
  );
  return { run: data, accepted: status === 202 };
}

/** Lists the runs of a dataset, newest first. */
export function listValidationRuns(
  datasetId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<{ items: ValidationRunSummary[] }> {
  return apiClient.get(apiPath`/datasets/${datasetId}/validation-runs`, {
    signal,
  });
}

/** Loads a run with its plan, detector reports and issue counts. */
export function getValidationRun(
  runId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<ValidationRunDetail> {
  return apiClient.get(apiPath`/validation-runs/${runId}`, { signal });
}

/** Marks a run as review-finished after all findings were decided. */
export function finishValidationRunReview(
  runId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<ValidationRunDetail> {
  return apiClient.post(apiPath`/validation-runs/${runId}/review-finish`, { json: {}, signal });
}

/** Reopens a finished run review, so findings can be revised again. */
export function reopenValidationRunReview(
  runId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<ValidationRunDetail> {
  return apiClient.delete(apiPath`/validation-runs/${runId}/review-finish`, { signal });
}

/**
 * Loads the risk report of a finished run (docs/api/rest-api.md#risk-report). Reading and
 * re-sorting never call a model and never start discovery: switch `sortBy` / `sortOrder` with
 * the same `discoveryRunId`; the backend re-reads the rule checks and the stored run.
 *
 * `rank` is the displayed position, `priority_rank` the default one. Show `sortBy`
 * `confidence` as "evidence certainty" (证据确定程度), never as a probability or accuracy.
 */
export function getRiskReport(
  runId: string,
  {
    sortBy = "priority",
    sortOrder = "desc",
    discoveryRunId,
  }: { sortBy?: "priority" | "price_impact" | "confidence"; sortOrder?: "desc" | "asc"; discoveryRunId?: string } = {},
  { signal }: { signal?: AbortSignal } = {},
): Promise<RiskReport> {
  return apiClient.get(apiPath`/validation-runs/${runId}/risks`, {
    query: {
      sort_by: sortBy,
      sort_order: sortOrder,
      discovery_run_id: discoveryRunId,
    },
    signal,
  });
}

/**
 * Starts budgeted discovery by the local model once, in the background (`Prefer:
 * respond-async`); poll {@link getRiskDiscoveryRun} until `status` is `finished` or `failed`.
 * A second start for the same inputs returns the run that exists (`started` false), so a double
 * click starts nothing new; `rerun` asks for a new run explicitly.
 */
export async function startRiskDiscovery(
  runId: string,
  { strategy = "paths", rerun = false }: { strategy?: "paths" | "sample"; rerun?: boolean } = {},
  { signal }: { signal?: AbortSignal } = {},
): Promise<{ run: DiscoveryRun; started: boolean }> {
  const { data, status } = await requestJsonResponse<DiscoveryRun>(
    apiPath`/validation-runs/${runId}/risks/discovery-runs`,
    {
      method: "POST",
      json: { strategy, rerun },
      headers: { Prefer: "respond-async" },
      signal,
    },
  );
  return { run: data, started: status !== 200 };
}

/** One stored discovery run; reading it never calls a model. */
export function getRiskDiscoveryRun(
  runId: string,
  discoveryRunId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<DiscoveryRun> {
  return apiClient.get(
    apiPath`/validation-runs/${runId}/risks/discovery-runs/${discoveryRunId}`,
    { signal },
  );
}

/**
 * The latest decision on each reminder without a finding in the run's document (risks with
 * findings are decided through their findings).
 */
export function listRiskReviews(
  runId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<{ run_id: string; items: RiskReview[] }> {
  return apiClient.get(apiPath`/validation-runs/${runId}/risk-reviews`, { signal });
}

/**
 * Records a decision on a reminder without a finding: `open` (takes a decision back),
 * `in_review`, `approved` or `rejected`.
 */
export function saveRiskReview(
  runId: string,
  riskId: string,
  { status, comment = '' }: { status: RiskReview['status']; comment?: string },
  { signal }: { signal?: AbortSignal } = {},
): Promise<RiskReview> {
  return apiClient.put(apiPath`/validation-runs/${runId}/risk-reviews/${riskId}`, { json: { status, comment }, signal });
}
