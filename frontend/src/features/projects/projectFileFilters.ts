/** The search and filters over a project's files table, without React. */
import { msg } from '../../i18n/messages.ts';
import { matchesSearch } from '../../utils/textSearch.ts';
import type { DocumentSummary, ReviewCounts } from '../../services/apiTypes.ts';

/** What a file is in its project: a bill, a reference the bills are compared with, or a supporting document. */
export type FileType = 'bill' | 'reference' | 'support';

export interface FileFilters {
  /** words found in the file's name */
  search: string;
  /** '' for every type */
  type: '' | FileType;
  /** '' for every state */
  state: '' | 'review' | 'high' | 'attention';
}

export const NO_FILE_FILTERS: Readonly<FileFilters> = Object.freeze({ search: '', type: '', state: '' });

export const FILE_TYPES = Object.freeze<{ value: FileType; label: string }[]>([
  { value: 'bill', label: msg('Bills') },
  { value: 'reference', label: msg('projects.file.references') },
  { value: 'support', label: msg('Supporting documents') },
]);

export const FILE_STATES = Object.freeze<{ value: Exclude<FileFilters['state'], ''>; label: string }[]>([
  { value: 'review', label: msg('Findings to review') },
  { value: 'high', label: msg('High-priority findings') },
  { value: 'attention', label: msg('Needing attention') },
]);

/** A bill that could not be read, or whose last check failed. A reference or a supporting document never needs it. */
export function needsAttention(doc: Pick<DocumentSummary, 'processing_status' | 'last_run'>, type: FileType = 'bill'): boolean {
  if (type !== 'bill') return false;
  const run = doc.last_run?.status;
  return (
    doc.processing_status === 'failed' ||
    doc.processing_status === 'needs_review' ||
    run === 'failed' ||
    run === 'completed_with_errors'
  );
}

/** The files that meet every filter, the newest upload first, then by name. */
export function filterFiles(
  documents: readonly DocumentSummary[],
  filters: FileFilters,
  typeOf: (doc: DocumentSummary) => FileType,
  reviewCounts: ReviewCounts,
): DocumentSummary[] {
  const meetsState = (doc: DocumentSummary) => {
    const counts = reviewCounts[doc.document_id];
    if (filters.state === 'review') return (counts?.to_review ?? 0) > 0;
    if (filters.state === 'high') return (counts?.high_priority ?? 0) > 0;
    if (filters.state === 'attention') return needsAttention(doc, typeOf(doc));
    return true;
  };
  return documents
    .filter((doc) => (!filters.type || typeOf(doc) === filters.type) && meetsState(doc) && matchesSearch(filters.search, [doc.original_filename]))
    .sort((a, b) => Date.parse(b.uploaded_at) - Date.parse(a.uploaded_at) || a.original_filename.localeCompare(b.original_filename));
}
