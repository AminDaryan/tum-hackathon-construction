import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { runDetail } from '../../test/fixtures.ts';
import { countDetectorStatuses } from './detectorCounts.ts';
import { RunValidationStatus } from './RunValidationStatus.tsx';
import type { DetectorRunReport, ValidationRunDetail } from '../../services/apiTypes.ts';

// A detector the time limit stopped reports `stopped` (docs/api/rest-api.md, "Validation runs")
// and its run ends `completed_with_errors`, so the counts must not leave it out.
const [report] = runDetail.detector_reports;
const reports: DetectorRunReport[] = [
  { ...report, status: 'completed' },
  { ...report, detector_id: 'deterministic.subtotal', status: 'completed' },
  { ...report, detector_id: 'deterministic.unit_vocabulary', status: 'skipped' },
  { ...report, detector_id: 'deterministic.grand_total', status: 'stopped', limit_reached: 'time' },
];

describe('detector status counts', () => {
  it('counts every execution status the API reports, stopped included', () => {
    expect(countDetectorStatuses(reports)).toEqual({ completed: 2, skipped: 1, failed: 0, stopped: 1 });
  });

  it('names the stopped detector in the outcome of a run', () => {
    const run: ValidationRunDetail = { ...runDetail, status: 'completed_with_errors', issue_count: 2, detector_reports: reports };
    render(
      <MemoryRouter>
        <RunValidationStatus pending={false} error={null} result={run} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('status')).toHaveTextContent(
      'Validation run finished with 2 issues. 2 detectors completed, 1 skipped, 0 failed, 1 stopped.',
    );
  });

  it('speaks of one detector in the singular', () => {
    const run: ValidationRunDetail = { ...runDetail, status: 'completed', issue_count: 1, detector_reports: [reports[0]] };
    render(
      <MemoryRouter>
        <RunValidationStatus pending={false} error={null} result={run} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('status')).toHaveTextContent(
      'Validation run finished with 1 issue. 1 detector completed, 0 skipped, 0 failed.',
    );
  });
});
