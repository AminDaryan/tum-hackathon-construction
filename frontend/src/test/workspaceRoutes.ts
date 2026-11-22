/**
 * Routes of an open tender.xlsx in the workspace, shared by the workspace page tests.
 */
import { page, type MockResponse, type MockRoute } from './fetchMock.ts';
import type { Project } from '../services/apiTypes.ts';
import {
  detectorCatalogue,
  documentDetail,
  documentSummary,
  issueHistory,
  lineTotalIssue,
  outlierIssue,
  problemList,
  riskReport,
  rowsPage,
  runDetail,
} from './fixtures.ts';

export const ROWS = '/api/v1/datasets/ds_1/tables/tbl_1/rows';
export const RUNS = '/api/v1/datasets/ds_1/validation-runs';
export const ISSUES = '/api/v1/validation-runs/run_2/issues';
export const RISKS = '/api/v1/validation-runs/run_2/risks';
export const RISK_REVIEWS = '/api/v1/validation-runs/run_2/risk-reviews';

/**
 * @param options `runs` is what GET validation-runs lists;
 *   routes in `extra` take precedence
 */
export function workspaceRoutes({
  detail = documentDetail,
  rowsRespond = rowsPage,
  runs = () => [],
  issues = [lineTotalIssue, outlierIssue],
  report = riskReport,
  extra = [],
}: {
  detail?: MockResponse;
  rowsRespond?: MockResponse;
  runs?: () => unknown[];
  issues?: unknown[];
  report?: MockResponse;
  extra?: MockRoute[];
} = {}): MockRoute[] {
  return [
    ...extra,
    { path: '/api/v1/documents/doc_1', respond: detail },
    { path: ROWS, respond: rowsRespond },
    { path: RUNS, respond: () => ({ items: runs() }) },
    { path: '/api/v1/validation-runs/run_2', respond: runDetail },
    { path: ISSUES, respond: page(issues, { limit: 500 }) },
    { path: RISKS, respond: report },
    { path: RISK_REVIEWS, respond: { run_id: 'run_2', items: [] } },
    { path: '/api/v1/validation-runs/run_2/problems', respond: problemList },
    { path: '/api/v1/issues/iss_1', respond: { issue: lineTotalIssue, history: issueHistory } },
    { path: '/api/v1/issues/iss_2', respond: { issue: outlierIssue, history: issueHistory } },
    { path: '/api/v1/detectors', respond: detectorCatalogue },
  ];
}

/** The project tender.xlsx belongs to, whose Workspace opens it. */
export const WORKSPACE_PROJECT = Object.freeze<Project>({
  project_id: 'prj_1',
  name: 'Riverside',
  description: '',
  created_at: '2026-11-21T10:00:00Z',
  status: 'in_progress',
  assignees: [],
  decision_cutoff: null,
  files: [{ document_id: 'doc_1', role: 'bill' }],
  demo_key: null,
  preparation: 'ready',
  preparation_error: null,
  validation: null,
});

/** tender.xlsx open in the Workspace of its project. */
export const WORKSPACE_URL = '/projects/prj_1/workspace?document=doc_1';

/** The routes of `workspaceRoutes` and of the project the file is opened in (after them). */
export function projectWorkspaceRoutes(options: Parameters<typeof workspaceRoutes>[0] = {}): MockRoute[] {
  return [
    ...workspaceRoutes(options),
    { path: '/api/v1/projects/prj_1', respond: { project: WORKSPACE_PROJECT, documents: [documentSummary], review_counts: {} } },
    { path: '/api/v1/projects/prj_1/clarifications', respond: { items: [], total: 0, offset: 0, limit: 10 } },
    { path: '/api/v1/projects', respond: [WORKSPACE_PROJECT] },
  ];
}
