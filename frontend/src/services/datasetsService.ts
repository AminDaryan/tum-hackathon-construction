/**
 * Datasets: table rows and the workspace summary (docs/api/rest-api.md#datasets).
 */
import { apiClient, apiPath } from './apiClient.ts';
import type { CorrectionsResult, Page, Row } from './apiTypes.ts';

/**
 * Loads one page of canonical rows of a table.
 *
 * @param page limit ≤ 1000
 */
export function getTableRows(
  datasetId: string,
  tableId: string,
  { offset = 0, limit = 100, rowId }: { offset?: number; limit?: number; rowId?: string } = {},
  { signal }: { signal?: AbortSignal } = {},
): Promise<Page<Row>> {
  return apiClient.get(apiPath`/datasets/${datasetId}/tables/${tableId}/rows`, {
    query: rowId ? { limit, row_id: rowId } : { offset, limit },
    signal,
  });
}

/**
 * Saves corrected cell texts as the dataset's next revision (the uploaded file is not changed).
 * Answers `{ dataset_id, revision, parent_revision, changed, rows }`; 409 `conflict` when
 * `expectedRevision` is not the latest revision.
 */
export function correctCells(
  datasetId: string,
  {
    expectedRevision,
    corrections,
  }: { expectedRevision: number; corrections: { table_id: string; row_id: string; column_id: string; raw_value: string }[] },
  { signal }: { signal?: AbortSignal } = {},
): Promise<CorrectionsResult> {
  return apiClient.post(apiPath`/datasets/${datasetId}/corrections`, {
    json: { expected_revision: expectedRevision, corrections },
    signal,
  });
}
