import { getTableRows } from '../../services/datasetsService.ts';
import type { DatasetSummary, Row } from '../../services/apiTypes.ts';
import { materialQuantities, type MaterialTable } from './materialQuantities.ts';

/** Read every table, not only the sheet's current page. Abort discards the whole result. */
export async function loadMaterialQuantities(
  dataset: Pick<DatasetSummary, 'dataset_id' | 'tables'>,
  signal?: AbortSignal,
) {
  const tables: MaterialTable[] = [];
  for (const table of dataset.tables) {
    const rows: Row[] = [];
    let total: number;
    do {
      const page = await getTableRows(dataset.dataset_id, table.table_id, { offset: rows.length, limit: 1000 }, { signal });
      total = page.total;
      if (!page.items.length && rows.length < total) throw new Error('Incomplete table response');
      rows.push(...page.items);
    } while (rows.length < total);
    tables.push({ table, rows });
  }
  return materialQuantities(tables);
}
