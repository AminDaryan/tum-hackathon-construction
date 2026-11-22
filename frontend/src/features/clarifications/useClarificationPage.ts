import { useApiResource } from '../../hooks/useApiResource.ts';
import {
  listClarifications,
  type Clarification,
  type ClarificationItem,
  type ClarificationPage,
  type ClarificationQuery,
} from '../../services/clarificationsService.ts';

/**
 * The page with a clarification the server just saved in it: in place of its earlier version, or
 * of the question it raised. Shown at once, while the page loads again.
 */
export function withSaved(page: ClarificationPage, saved: Clarification): ClarificationPage {
  const isSaved = (item: ClarificationItem) =>
    item.clarification_id === null
      ? item.document_id === saved.document_id && item.risk_id === saved.risk_id
      : item.clarification_id === saved.clarification_id;
  return { ...page, items: page.items.map((item) => (isSaved(item) ? saved : item)) };
}

export const clarificationKey = (item: ClarificationItem) => item.clarification_id ?? `${item.document_id}/${item.risk_id}`;

/**
 * One page of a project's clarifications and of the questions its risks ask that are not raised
 * yet, the most urgent first, as the server pages, searches and filters them.
 */
export function useClarificationPage(projectId: string, query: ClarificationQuery) {
  const { offset, limit, search, phase, kind, status, due_by: dueBy } = query;
  return useApiResource(
    (signal) => listClarifications(projectId, query, signal),
    [projectId, offset, limit, search, phase, kind, status, dueBy],
  );
}
