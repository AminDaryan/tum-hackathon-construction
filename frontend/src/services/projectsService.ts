import { apiClient, apiPath, sendRequest } from './apiClient.ts';
import { filenameFromContentDisposition } from '../utils/contentDisposition.ts';
import { saveBlob } from '../utils/download.ts';
import type { BidReport, FileGroup, Project, ProjectDetail, ValidationIssue } from './apiTypes.ts';

export const listProjects = (signal?: AbortSignal) => apiClient.get<Project[]>('/projects', { signal });
export const getProject = (id: string, signal?: AbortSignal) => apiClient.get<ProjectDetail>(apiPath`/projects/${id}`, { signal });
export const createProject = (
  { name, description = '', assignees = [] }: { name: string; description?: string; assignees?: string[] },
  signal?: AbortSignal,
) => apiClient.post<Project>('/projects', { json: { name, description, assignees }, signal });
export const updateProject = (
  id: string,
  changes: { name?: string; description?: string; assignees?: string[]; status?: 'in_progress' | 'finished'; decision_cutoff?: string | null },
  signal?: AbortSignal,
) => apiClient.patch<Project>(apiPath`/projects/${id}`, { json: changes, signal });
export const addProjectFile = (id: string, documentId: string, role = 'bill', signal?: AbortSignal) =>
  apiClient.put<Project>(apiPath`/projects/${id}/documents`, { json: { document_id: documentId, role }, signal });
export const moveProjectFile = (id: string, documentId: string, group: FileGroup, signal?: AbortSignal) =>
  apiClient.patch<Project>(apiPath`/projects/${id}/documents/${documentId}`, { json: { group }, signal });
export const removeProjectFile = (id: string, documentId: string, signal?: AbortSignal) =>
  apiClient.delete<Project>(apiPath`/projects/${id}/documents/${documentId}`, { signal });
export const validateProject = (id: string, signal?: AbortSignal) => apiClient.post<Project>(apiPath`/projects/${id}/validation`, { signal });
/** The bid risk report of the project's last validation; 409 before it is validated. */
export const getProjectRiskReport = (id: string, limit = 20, signal?: AbortSignal) =>
  apiClient.get<BidReport>(apiPath`/projects/${id}/risk-report`, { query: { limit }, signal });

/**
 * A page of the findings still to review over the bills of the project's last validation, the
 * most severe first, then the largest financial impact; `total` counts them all. 409 before the
 * project is validated or while it runs.
 */
export const listTopIssues = (id: string, { limit, offset }: { limit: number; offset: number }, signal?: AbortSignal) =>
  apiClient.get<{ items: ValidationIssue[]; total: number }>(apiPath`/projects/${id}/top-issues`, { query: { limit, offset }, signal });

/** A report generated on the Reports page and kept in the project. */
export interface ProjectReport {
  report_id: string;
  created_at: string;
  /** the findings as a file, or the bid risk report (`bid-risk.pdf`, the whole project only) */
  format: 'pdf' | 'xlsx' | 'issues.csv' | 'bid-risk.pdf';
  /** the bill it covers; null for the whole project */
  document_id: string | null;
  filename: string;
  media_type: string;
  size_bytes: number;
  validated_at: string | null;
}

export const listReports = (id: string, signal?: AbortSignal) =>
  apiClient.get<{ items: ProjectReport[] }>(apiPath`/projects/${id}/reports`, { signal });
/** Generates a report on the last validation (the whole project, or one bill) and keeps it. */
export const createReport = (id: string, format: ProjectReport['format'], documentId: string | null, signal?: AbortSignal) =>
  apiClient.post<ProjectReport>(apiPath`/projects/${id}/reports`, { json: { format, document_id: documentId }, signal });
/** Downloads a kept report to the user's computer under its file name. */
export async function downloadReport(id: string, report: ProjectReport, { signal }: { signal?: AbortSignal } = {}) {
  const response = await sendRequest(apiPath`/projects/${id}/reports/${report.report_id}/file`, { signal });
  const blob = await response.blob();
  const filename = filenameFromContentDisposition(response.headers.get('Content-Disposition')) ?? report.filename;
  saveBlob(blob, filename);
  return { filename, size: blob.size };
}
