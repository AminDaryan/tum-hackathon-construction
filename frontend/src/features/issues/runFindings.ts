/**
 * The findings of a run as the workspace shows them: loaded in full (up to a cap), grouped by
 * the check that raised them, and indexed by row and cell so the table preview can mark where
 * they are.
 */
import { listRunIssues } from '../../services/issuesService.ts';
import { SEVERITY_META } from '../../utils/vocabulary.ts';
import type { ValidationIssue } from '../../services/apiTypes.ts';

/** The API's largest page. */
const FINDINGS_PAGE_SIZE = 500;

/** Findings loaded for the workspace; the issue register pages through any beyond. */
const MAX_FINDINGS = 2000;

/**
 * Loads a run's findings page by page (in the API's order: severity, table, source row).
 */
export async function loadRunFindings(
  runId: string,
  { signal, max = MAX_FINDINGS }: { signal?: AbortSignal; max?: number } = {},
): Promise<{ items: ValidationIssue[], total: number }> {
  const items = [];
  let total = 0;
  while (items.length < max) {
    const limit = Math.min(FINDINGS_PAGE_SIZE, max - items.length);
    const page = await listRunIssues(runId, { offset: items.length, limit }, { signal });
    items.push(...page.items);
    total = page.total;
    if (!page.items.length || items.length >= total) break;
  }
  return { items, total };
}

// How strong a finding's evidence is: a reviewer's confirmation, then a broken rule, then the
// signals in the order the vocabulary lists them.
const CLASS_RANK: Readonly<Record<string, number>> = Object.freeze({
  human_confirmed_error: 0,
  confirmed_rule_violation: 1,
  suspected_anomaly: 2,
  semantic_warning: 3,
  extraction_uncertainty: 4,
  needs_external_context: 5,
});

function severityRank(issue: ValidationIssue) {
  return SEVERITY_META[issue.severity]?.rank ?? 0;
}

function classRank(issue: ValidationIssue) {
  return CLASS_RANK[issue.effective_evidence_class] ?? Object.keys(CLASS_RANK).length;
}

/** Sort order of findings: higher severity first, then stronger evidence. */
export function compareFindings(a: ValidationIssue, b: ValidationIssue): number {
  return severityRank(b) - severityRank(a) || classRank(a) - classRank(b);
}

const EMPTY: readonly ValidationIssue[] = Object.freeze([]);
const rowKey = (tableId: string, rowId: string) => `${tableId}\u0000${rowId}`;
const cellKey = (tableId: string, rowId: string, columnId: string) => `${tableId}\u0000${rowId}\u0000${columnId}`;

/**
 * Where findings are: the rows a finding names or highlights, and its highlighted cells.
 */
export function indexFindings(issues: ValidationIssue[]): FindingsIndex {
  const rows = new Map<string, ValidationIssue[]>();
  const cells = new Map<string, ValidationIssue>();
  for (const issue of issues) {
    const keys = new Set<string>();
    if (issue.table_id && issue.row_id) keys.add(rowKey(issue.table_id, issue.row_id));
    for (const cell of issue.affected_cells ?? []) {
      if (!cell.table_id || !cell.row_id) continue;
      keys.add(rowKey(cell.table_id, cell.row_id));
      if (cell.column_id) {
        const key = cellKey(cell.table_id, cell.row_id, cell.column_id);
        const current = cells.get(key);
        if (!current || compareFindings(issue, current) < 0) cells.set(key, issue);
      }
    }
    for (const key of keys) {
      if (!rows.has(key)) rows.set(key, []);
      rows.get(key)!.push(issue);
    }
  }
  return {
    size: issues.length,
    forRow: (tableId, rowId) => rows.get(rowKey(tableId, rowId)) ?? EMPTY,
    forCell: (tableId, rowId, columnId) => cells.get(cellKey(tableId, rowId, columnId)) ?? null,
  };
}

/** An index without findings (before the first run, or while they load). */
export const NO_FINDINGS = indexFindings([]);

/** Where findings are: the result of {@link indexFindings}. */
export interface FindingsIndex {
  size: number;
  forRow: (tableId: string, rowId: string) => readonly ValidationIssue[];
  forCell: (tableId: string, rowId: string, columnId: string) => ValidationIssue | null;
}
