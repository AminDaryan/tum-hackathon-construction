import { useCallback, useState } from 'react';
import { useApiResource } from '../../../hooks/useApiResource.ts';
import { getTableRows } from '../../../services/datasetsService.ts';
import type { Row } from '../../../services/apiTypes.ts';
import { SHEET_PAGE_SIZE } from './sheetMoves.ts';

/**
 * The page of rows the sheet shows. A page is asked for by its offset (paging) or by a row it
 * must hold (`showRow`, for an issue on another page): the server then answers the page with
 * that row and says its offset.
 *
 * `ready` is true once the rows on hand answer the current request, so a caller waiting for a
 * row can tell "still loading" from "not on this page".
 */
export function useSheetRows({
  datasetId,
  tableId,
  initialRowId = null,
  pageSize = SHEET_PAGE_SIZE,
}: {
  datasetId: string;
  tableId: string;
  initialRowId?: string | null;
  pageSize?: number;
}) {
  const [request, setRequest] = useState<{ offset: number; rowId: string | null }>(() => ({ offset: 0, rowId: initialRowId }));
  const requestKey = request.rowId ? `row:${request.rowId}` : `offset:${request.offset}`;
  const resource = useApiResource(
    async (signal) => {
      const page = await getTableRows(
        datasetId,
        tableId,
        request.rowId ? { rowId: request.rowId, limit: pageSize } : { offset: request.offset, limit: pageSize },
        { signal },
      );
      return { page, requestKey };
    },
    [datasetId, tableId, requestKey, pageSize],
  );

  const { setData } = resource;
  const data = resource.data;
  const goToPage = useCallback((offset: number) => setRequest({ offset, rowId: null }), []);
  const showRow = useCallback(
    (rowId: string) => setRequest((current) => (current.rowId === rowId ? current : { offset: current.offset, rowId })),
    [],
  );
  const applyRows = useCallback(
    (changed: Row[]) => {
      const byId = new Map(changed.map((row) => [row.row_id, row]));
      setData((current) =>
        current
          ? { ...current, page: { ...current.page, items: current.page.items.map((row) => byId.get(row.row_id) ?? row) } }
          : current,
      );
    },
    [setData],
  );

  return {
    rows: data?.page.items ?? null,
    total: data?.page.total ?? null,
    offset: data?.page.offset ?? request.offset,
    ready: data?.requestKey === requestKey,
    loading: resource.loading,
    error: resource.error,
    requestedRowId: request.rowId,
    goToPage,
    showRow,
    applyRows,
    reload: resource.reload,
  };
}
