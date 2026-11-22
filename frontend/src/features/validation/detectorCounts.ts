/**
 * Counts detector reports by execution status: every status a detector report can have
 * (`stopped` is a detector the run's time limit stopped; its findings so far are kept).
 */
export function countDetectorStatuses(
  reports: Array<{ status: string }> = [],
): { completed: number, skipped: number, failed: number, stopped: number } {
  const counts = { completed: 0, skipped: 0, failed: 0, stopped: 0 };
  for (const report of reports) {
    if (report.status in counts) {
      counts[report.status as keyof typeof counts] += 1;
    }
  }
  return counts;
}
