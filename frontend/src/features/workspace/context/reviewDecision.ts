/**
 * Saving a review decision, shared by the decision bar of the Risks tab and the quick decisions
 * of AI Risk Insights. A decision the server refuses as stale (the issue changed in the
 * meantime) is not an error: the issue is reloaded and the reviewer decides again.
 */
import { msg } from '../../../i18n/messages.ts';
import { ApiError } from '../../../services/apiClient.ts';
import { getIssue, submitReview } from '../../../services/issuesService.ts';
import type { IssueDetail } from '../../../services/apiTypes.ts';

const STALE_CODES = new Set(['conflict', 'invalid_review_transition']);

export const STALE_MESSAGE = msg('This risk was changed in the meantime and has been reloaded. Decide again.');

/**
 * @param issue the copy the reviewer saw
 */
export async function saveDecision(
  issue: { issue_id: string; version: number },
  status: string,
  comment: string,
  signal?: AbortSignal,
): Promise<{ detail: IssueDetail, stale: boolean }> {
  try {
    const detail = await submitReview(issue.issue_id, { status, comment, expectedVersion: issue.version }, { signal });
    return { detail, stale: false };
  } catch (error) {
    if (!(error instanceof ApiError) || !STALE_CODES.has(error.code)) throw error;
    return { detail: await getIssue(issue.issue_id, { signal }), stale: true };
  }
}
