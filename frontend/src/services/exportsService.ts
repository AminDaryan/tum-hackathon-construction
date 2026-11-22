/**
 * Exports (docs/api/rest-api.md#exports): of a validation run, the issues as CSV, every table as
 * CSV in a ZIP, an Excel workbook (tables, issues, extraction report), the JSON export and a PDF
 * findings report; of a dataset, the extracted tables as an Excel workbook (no run needed); of a
 * project, the findings of its last validation as a PDF report, an Excel workbook or a CSV file,
 * and its bid risk report as a PDF.
 */
import { filenameFromContentDisposition } from '../utils/contentDisposition.ts';
import { saveBlob } from '../utils/download.ts';
import { apiPath, sendRequest } from './apiClient.ts';

/** The exports of a run: the last URL segment and the download name when the server sends none. */
export const RUN_EXPORTS = Object.freeze({
  csv: { file: 'issues.csv', fallback: (runId: string) => `validation-run-${runId}-issues.csv` },
  zip: { file: 'tables.zip', fallback: (runId: string) => `validation-run-${runId}-tables.zip` },
  json: { file: 'json', fallback: (runId: string) => `validation-run-${runId}.json` },
  xlsx: { file: 'xlsx', fallback: (runId: string) => `validation-run-${runId}.xlsx` },
  questions: { file: 'questions.md', fallback: (runId: string) => `validation-run-${runId}-questions.md` },
  pdf: { file: 'pdf', fallback: (runId: string) => `validation-run-${runId}-report.pdf` },
});

export type RunExportKind = keyof typeof RUN_EXPORTS;

/** The exports of a project: the last URL segment and the download name when the server sends none. */
export const PROJECT_EXPORTS = Object.freeze({
  pdf: { file: 'pdf', fallback: (projectId: string) => `project-${projectId}-report.pdf` },
  xlsx: { file: 'xlsx', fallback: (projectId: string) => `project-${projectId}-issues.xlsx` },
  csv: { file: 'issues.csv', fallback: (projectId: string) => `project-${projectId}-issues.csv` },
});

export type ProjectExportKind = keyof typeof PROJECT_EXPORTS;

/** What a download saved. */
export interface SavedDownload {
  filename: string;
  size: number;
}

/** Downloads the findings of every bill in a project's last validation, as one file. */
export async function downloadProjectExport(
  projectId: string,
  kind: ProjectExportKind,
  { signal }: { signal?: AbortSignal } = {},
): Promise<SavedDownload> {
  const { file, fallback } = PROJECT_EXPORTS[kind];
  const response = await sendRequest(apiPath`/projects/${projectId}/export/${file}`, { signal });
  return save(response, fallback(projectId));
}

/**
 * Downloads one export of a run to the user's computer (fetch -> Blob -> object URL), under the
 * filename the server suggests in Content-Disposition.
 */
export async function downloadRunExport(
  runId: string,
  kind: RunExportKind,
  { signal }: { signal?: AbortSignal } = {},
): Promise<SavedDownload> {
  const { file, fallback } = RUN_EXPORTS[kind];
  const response = await sendRequest(apiPath`/validation-runs/${runId}/export/${file}`, { signal });
  return save(response, fallback(runId));
}

/**
 * Downloads the extracted tables of a dataset as an Excel workbook (one sheet per table and an
 * Extraction sheet), without a validation run.
 */
export async function downloadDatasetExcel(
  datasetId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<SavedDownload> {
  const response = await sendRequest(apiPath`/datasets/${datasetId}/export/xlsx`, { signal });
  return save(response, `dataset-${datasetId}-extracted.xlsx`);
}

async function save(response: Response, fallbackName: string): Promise<SavedDownload> {
  const blob = await response.blob();
  const filename = filenameFromContentDisposition(response.headers.get('Content-Disposition')) ?? fallbackName;
  saveBlob(blob, filename);
  return { filename, size: blob.size };
}
