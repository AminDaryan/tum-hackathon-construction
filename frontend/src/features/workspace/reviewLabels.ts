/**
 * How the workspace names review states and decisions. Approve marks a finding as a real issue
 * (`confirmed_error`); Reject marks it as not an issue, to be ignored (`false_positive`).
 * The global vocabulary (Settings, exports) keeps its own wording.
 */
import { msg, t } from '../../i18n/messages.ts';

const REVIEW_STATE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  pending_review: msg('To review'),
  confirmed_error: msg('Approved'),
  false_positive: msg('Rejected'),
  dismissed: msg('Rejected'),
  needs_more_information: msg('Needs clarification'),
  corrected: msg('Corrected'),
});

/** Review states whose finding no longer marks its cells (decided as not an issue, or fixed). */
const CLOSED_STATES: ReadonlySet<string> = Object.freeze(new Set(['false_positive', 'dismissed', 'corrected']));

/**
 * @returns whether the finding still marks its cells red
 */
export function isOpenFinding(issue: { review_status?: string }): boolean {
  return !CLOSED_STATES.has(issue.review_status ?? '');
}

/**
 * @returns whether nobody has decided the finding yet
 */
export function isToReview(issue: { review_status?: string }): boolean {
  return (issue.review_status ?? 'pending_review') === 'pending_review';
}

export function reviewStateLabel(status: string) {
  return t(REVIEW_STATE_LABELS[status]) ?? status;
}

/** The decisions of the issue window, in button order. */
export const DECISIONS = Object.freeze([
  { status: 'confirmed_error', label: msg('Approve'), hint: msg('It is a real issue') },
  { status: 'false_positive', label: msg('Reject'), hint: msg('Not an issue, ignore it') },
  { status: 'needs_more_information', label: msg('Needs clarification'), hint: null },
]);
