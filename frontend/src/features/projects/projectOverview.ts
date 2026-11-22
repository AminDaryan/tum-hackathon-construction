import { msg, t } from '../../i18n/messages.ts';
import { formatCount } from '../../utils/format.ts';
import type { DocumentSummary, FileGroup, Project, ProjectFile, ReviewCounts } from '../../services/apiTypes.ts';

type Doc = Pick<DocumentSummary, 'document_id'>;

/** One figure of the project overview. */
export interface ProjectFigure {
  label: string;
  /** null while the project loads */
  value: string | null;
  tone?: 'danger' | 'warning' | 'neutral';
}

/** Projects, the newest first (as Projects and the sidebar list them). */
export function newestFirst<P extends Pick<Project, 'created_at'>>(projects: readonly P[]): P[] {
  return [...projects].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
}

/** The role of a file in the project: 'bill' (the default) or 'reference'. */
export function roleOf(project: Pick<Project, 'files'>, doc: Doc): ProjectFile['role'] {
  return project.files.find((file) => file.document_id === doc.document_id)?.role ?? 'bill';
}

/**
 * Whether a file is a bill (the table view) or a supporting document (opened as the document
 * itself), as the server decided in `ProjectDetail.groups`; a bill when it did not say.
 */
export function groupOf(groups: Record<string, FileGroup> | undefined, doc: Doc): FileGroup {
  return groups?.[doc.document_id] ?? 'bill';
}

/** The project's bills that were read into a table, the ones a validation checks. */
export function readableBills<D extends Pick<DocumentSummary, 'document_id' | 'dataset_id'>>(
  project: Pick<Project, 'files'>,
  documents: D[],
): D[] {
  return documents.filter((doc) => doc.dataset_id && roleOf(project, doc) !== 'reference');
}

/** Sums of the review counts over the project's bills: all findings, those to review, the high ones among them. */
export function projectTotals(reviewCounts: ReviewCounts): { findings: number; toReview: number; high: number } {
  return Object.values(reviewCounts).reduce(
    (sum, counts) => ({
      findings: sum.findings + (counts.findings ?? 0),
      toReview: sum.toReview + counts.to_review,
      high: sum.high + counts.high_priority,
    }),
    { findings: 0, toReview: 0, high: 0 },
  );
}

/** Every finding of the project's last validation by priority (`critical`, `high`, …), over its bills. */
export function findingsBySeverity(reviewCounts: ReviewCounts): Record<string, number> {
  const sums: Record<string, number> = {};
  for (const counts of Object.values(reviewCounts)) {
    for (const [severity, count] of Object.entries(counts.by_severity ?? {})) sums[severity] = (sums[severity] ?? 0) + count;
  }
  return sums;
}

/**
 * Whether a file's own check (an added file, a re-check after a change) is queued or running: the
 * project is read again until it ends, so its row's spinner stops.
 */
export function isCheckingAFile(documents: Pick<DocumentSummary, 'last_run'>[]): boolean {
  return documents.some((doc) => doc.last_run?.status === 'queued' || doc.last_run?.status === 'running');
}

/** Whether the project's last validation has a result for at least one bill. */
export function hasValidationResult(project: Pick<Project, 'validation'>): boolean {
  return Object.keys(project.validation?.runs ?? {}).length > 0;
}

/**
 * The three figures of the project overview, over the bills of its last validation: bills,
 * findings, and findings to review (in red when some are of high priority); before any bill has
 * a validation result the last two say "Not validated", not 0, which would read as a clean bill.
 * There is no money total: a bill uploaded in two formats would be counted twice. While the
 * project loads (`project` null) the figures are not known yet: their values are null.
 */
export function projectFigures({
  project,
  documents,
  reviewCounts,
  groups,
}: {
  project: Pick<Project, 'files' | 'validation'> | null;
  documents: Doc[];
  reviewCounts: ReviewCounts;
  groups?: Record<string, FileGroup>;
}): ProjectFigure[] {
  const bills = project ? documents.filter((doc) => groupOf(groups, doc) === 'bill' && roleOf(project, doc) !== 'reference') : [];
  const totals = projectTotals(reviewCounts);
  if (!project) {
    return [
      { label: msg('Bills'), value: null },
      { label: msg('Findings'), value: null },
      { label: msg('To review'), value: null },
    ];
  }
  if (!hasValidationResult(project)) {
    return [
      { label: msg('Bills'), value: formatCount(bills.length) },
      { label: msg('Findings'), value: t('Not validated') },
      { label: msg('To review'), value: t('Not validated') },
    ];
  }
  return [
    { label: msg('Bills'), value: formatCount(bills.length) },
    { label: msg('Findings'), value: formatCount(totals.findings) },
    {
      label: msg('To review'),
      value: formatCount(totals.toReview),
      tone: totals.high ? 'danger' : totals.toReview ? 'warning' : 'neutral',
    },
  ];
}
