import { describe, expect, it } from 'vitest';
import { findingsBySeverity, isCheckingAFile, projectFigures, projectTotals } from './projectOverview.ts';
import type { ProjectFile, ProjectValidation } from '../../services/apiTypes.ts';
const doc = (id: string, extra = {}) => ({ document_id: id, original_filename: `${id}.x83`, dataset_id: `ds_${id}`, ...extra });
const project = (
  validation: ProjectValidation | null,
  files: ProjectFile[] = [
    { document_id: 'a', role: 'bill' },
    { document_id: 'b', role: 'bill' },
  ],
) => ({
  files,
  preparation: 'ready',
  validation,
});
// A test validation: only what the figures read.
const done = (runs: Record<string, string>) =>
  ({ status: 'completed', runs, skipped: {}, comparisons: [{}, {}] }) as ProjectValidation;

describe('projectOverview', () => {
  it('reads the project again while a file of its own is queued or running, not after', () => {
    const run = (status: string) => ({ last_run: { run_id: 'run_1', status, finished_at: null, issue_count: 0 } });
    expect(isCheckingAFile([run('completed'), run('queued')])).toBe(true);
    expect(isCheckingAFile([run('running')])).toBe(true);
    expect(isCheckingAFile([run('completed'), run('failed'), { last_run: null }])).toBe(false);
  });

  it('sums the review counts over the bills', () => {
    expect(
      projectTotals({ a: { findings: 4, to_review: 2, high_priority: 1 }, b: { findings: 3, to_review: 0, high_priority: 0 } }),
    ).toEqual({ findings: 7, toReview: 2, high: 1 });
  });

  it('gives the three figures of the project', () => {
    const files: ProjectFile[] = [
      { document_id: 'a', role: 'bill' },
      { document_id: 'b', role: 'bill' },
      { document_id: 'r', role: 'reference' },
    ];
    const documents = [doc('a'), doc('b'), doc('r')];
    const before = projectFigures({ project: project(null, files), documents, reviewCounts: {} });
    expect(before.map((item) => [item.label, item.value, item.tone])).toEqual([
      ['Bills', '2', undefined],
      ['Findings', 'Not validated', undefined],
      ['To review', 'Not validated', undefined],
    ]);
    const counts = { a: { findings: 3, to_review: 2, high_priority: 0 }, b: { findings: 0, to_review: 0, high_priority: 0 } };
    const after = projectFigures({ project: project(done({ a: 'run_a', b: 'run_b' }), files), documents, reviewCounts: counts });
    expect(after.map((item) => [item.value, item.tone])).toEqual([
      ['2', undefined],
      ['3', undefined],
      ['2', 'warning'],
    ]);
  });

  it('sums the findings by priority over the bills', () => {
    expect(
      findingsBySeverity({
        a: { findings: 3, to_review: 1, high_priority: 1, by_severity: { high: 1, low: 2 } },
        b: { findings: 1, to_review: 0, high_priority: 0, by_severity: { low: 1 } },
        c: { findings: 0, to_review: 0, high_priority: 0 },
      }),
    ).toEqual({ high: 1, low: 3 });
  });
});
