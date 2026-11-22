import { apiClient, apiPath } from './apiClient.ts';

/** A question to settle before the bid decision, raised on a risk of one of the project's bills. */
export interface Clarification {
  clarification_id: string;
  project_id: string;
  /** the bill the risk is in */
  document_id: string;
  risk_id: string;
  /** the risk's review priority when the clarification was raised */
  tier: string;
  /** who is asked */
  kind: 'bidder_question' | 'subcontractor' | 'management';
  title: string;
  status: 'draft' | 'sent' | 'answered' | 'decided';
  /** the day the answer is needed, `YYYY-MM-DD` */
  due: string | null;
  phase: 'bid' | 'after_award';
  answer: string;
  created_at: string;
  updated_at: string;
  /** The email it was drafted as, when it was: the finding it is about, to whom, its text. */
  issue_id?: string | null;
  recipient?: string | null;
  subject?: string | null;
  body?: string | null;
  /** When the email was first opened in an email app or copied (ISO). */
  sent_at?: string | null;
}

/** An email drafted about a risk; `sent` once it was opened in an email app or copied. */
interface EmailClarification {
  document_id: string;
  risk_id: string;
  tier: string;
  title: string;
  issue_id?: string | null;
  recipient?: string;
  subject: string;
  body: string;
  sent?: boolean;
}

/**
 * A listed clarification, or a question a risk of the project's last validation asks the client
 * that is not raised yet: no id, a draft bidder question until saved.
 */
export type ClarificationItem = Omit<Clarification, 'clarification_id' | 'created_at' | 'updated_at'> & {
  clarification_id: string | null;
  created_at: string | null;
  updated_at: string | null;
};

/** The page and the search and filters of a listing; a filter left out keeps everything. */
export interface ClarificationQuery {
  offset: number;
  limit: number;
  /** words found in the item, its bill's name, its recipient or its answer */
  search?: string;
  phase?: Clarification['phase'];
  kind?: Clarification['kind'];
  /** `suggested`: a question not raised yet */
  status?: 'suggested' | Clarification['status'];
  /** not decided, and its answer needed by this day (`YYYY-MM-DD`) */
  due_by?: string;
}

/** One page of the clarifications and the questions not raised yet, the most urgent first. */
export interface ClarificationPage {
  items: ClarificationItem[];
  /** how many meet the query, on every page */
  total: number;
  offset: number;
  limit: number;
}

export const listClarifications = (projectId: string, query: ClarificationQuery, signal?: AbortSignal) =>
  apiClient.get<ClarificationPage>(apiPath`/projects/${projectId}/clarifications`, { query: { ...query }, signal });
/** Raises one on a risk; while that risk has an undecided one of the same kind, that one is returned. */
export const createClarification = (projectId: string, clarification: Partial<Clarification>, signal?: AbortSignal) =>
  apiClient.post<Clarification>(apiPath`/projects/${projectId}/clarifications`, { json: clarification, signal });
/** Lists the email as the risk's bidder question: its undecided one, else a new draft. */
export const recordEmailClarification = (projectId: string, email: EmailClarification, signal?: AbortSignal) =>
  apiClient.post<Clarification>(apiPath`/projects/${projectId}/clarifications/emails`, { json: email, signal });
/** Replaces all a reviewer sets: `{ kind, title, status, due, phase, answer }`. */
export const saveClarification = (
  id: string,
  fields: Pick<Clarification, 'kind' | 'title' | 'status' | 'due' | 'phase' | 'answer'>,
  signal?: AbortSignal,
) => apiClient.put<Clarification>(apiPath`/clarifications/${id}`, { json: fields, signal });
