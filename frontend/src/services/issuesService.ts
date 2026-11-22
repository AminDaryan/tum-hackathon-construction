/**
 * Issues and review decisions (docs/api/rest-api.md#issues).
 */
import { apiClient, apiPath } from './apiClient.ts';
import type { IssueCorrectionResult, IssueDetail, Page, ValidationIssue } from './apiTypes.ts';

/**
 * Repeatable issue filters accepted by GET /validation-runs/{run_id}/issues. Values within one
 * parameter are OR-ed, parameters are AND-ed; `evidence_class` matches the effective class, and
 * `finding_category` takes `none` for the findings without a category.
 */
const ISSUE_QUERY_FILTERS = Object.freeze([
  'severity',
  'evidence_class',
  'finding_category',
  'review_status',
  'detector_id',
  'category',
  'table_id',
  'row_id',
]);

/**
 * Lists the issues of a run (ordered by severity, table, source row, issue id).
 *
 * @param query limit ≤ 500
 */
export function listRunIssues(
  runId: string,
  { filters = {}, offset = 0, limit = 50 }: { filters?: Partial<Record<string, string[]>>; offset?: number; limit?: number } = {},
  { signal }: { signal?: AbortSignal } = {},
): Promise<Page<ValidationIssue>> {
  const query: Record<string, string[]> = {};
  for (const key of ISSUE_QUERY_FILTERS) {
    const values = filters[key];
    if (values?.length) {
      query[key] = values;
    }
  }
  return apiClient.get(apiPath`/validation-runs/${runId}/issues`, {
    query: { ...query, offset, limit },
    signal,
  });
}

/** Loads an issue with its audit history. */
export function getIssue(issueId: string, { signal }: { signal?: AbortSignal } = {}): Promise<IssueDetail> {
  return apiClient.get(apiPath`/issues/${issueId}`, { signal });
}

/**
 * Records a review decision. The dataset is never modified; the server appends an audit event
 * and answers 409 `invalid_review_transition` when the change is not allowed.
 *
 * @param decision `expectedVersion` is the `version` of the issue the reviewer saw; when the
 *   issue changed in the meantime the server answers 409 `conflict` and stores nothing. Empty
 *   comments are not sent.
 */
export function submitReview(
  issueId: string,
  { status, expectedVersion, comment }: { status: string; expectedVersion: number; comment?: string },
  { signal }: { signal?: AbortSignal } = {},
): Promise<IssueDetail> {
  const trimmed = typeof comment === 'string' ? comment.trim() : '';
  const json: { status: string; expected_version: number; comment?: string } = { status, expected_version: expectedVersion };
  if (trimmed) json.comment = trimmed;
  return apiClient.post(apiPath`/issues/${issueId}/review`, { json, signal });
}

/**
 * Applies one or more in-app value corrections, marks the issue as corrected, creates dataset
 * revision N+1 and (optionally) re-runs validation on that revision.
 */
export function submitCorrection(
  issueId: string,
  {
    expectedVersion,
    cells,
    comment,
    rerunValidation = true,
  }: {
    expectedVersion: number;
    cells: { table_id: string; row_id: string; column_id: string; value: string | null }[];
    comment?: string;
    rerunValidation?: boolean;
  },
  { signal }: { signal?: AbortSignal } = {},
): Promise<IssueCorrectionResult> {
  const trimmed = typeof comment === 'string' ? comment.trim() : '';
  const json: { expected_version: number; rerun_validation: boolean; cells: typeof cells; comment?: string } = {
    expected_version: expectedVersion,
    rerun_validation: rerunValidation,
    cells,
  };
  if (trimmed) json.comment = trimmed;
  return apiClient.post(apiPath`/issues/${issueId}/corrections`, { json, signal });
}
