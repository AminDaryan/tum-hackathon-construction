/**
 * The sheet's PDF view in a real browser: a GAEB bill from the sample data whose printed bill
 * is declared in src/features/workspace/sheet/pdfLinks.ts. The quantity of position 01.01.7
 * (200 St, PDF page 55) is chosen in the table; the PDF view shows the page in the same box
 * with that quantity highlighted, full screen draws it larger, and the table comes back
 * unchanged.
 */
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { openInProject } from './openInProject.ts';

const bill = fileURLToPath(new URL('../../Sample BoQ Dataset/8209.003_Leistungsverzeichnis_leer.X83', import.meta.url));

test('switch the sheet to the printed bill with the chosen cell highlighted', async ({ page }) => {
  await openInProject(page, bill, '8209.003_Leistungsverzeichnis_leer.X83');
  const grid = page.getByRole('grid');
  await expect(grid).toBeVisible();
  const sheet = page.locator('section').filter({ has: page.getByRole('group', { name: 'Active cell' }) });
  const tableHeight = (await sheet.boundingBox())!.height;

  const row = grid.getByRole('row').filter({ has: page.getByRole('gridcell', { name: '01.01.7', exact: true }) });
  await row.getByRole('gridcell', { name: '200.000', exact: true }).click();
  await page.getByRole('button', { name: 'PDF', exact: true }).click();

  await expect(page.getByRole('status').filter({ hasText: /^Menge of position 01\.01\.7 is highlighted on page 55\.$/ })).toBeVisible();
  await expect(page.getByTestId('pdf-cell')).toBeVisible();
  await expect(page.getByTestId('pdf-position')).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'PDF pages' })).toContainText('Page 55 of 136');
  expect((await sheet.boundingBox())!.height).toBe(tableHeight);

  // Full screen: the box covers the window and the page is drawn larger, still highlighted.
  const canvas = page.getByRole('img', { name: /^Page 55 of / });
  const pageWidth = (await canvas.boundingBox())!.width;
  await page.getByRole('button', { name: 'Full screen' }).click();
  const viewport = page.viewportSize()!;
  await expect.poll(async () => (await sheet.boundingBox())!.height).toBe(viewport.height);
  await expect.poll(async () => (await canvas.boundingBox())!.width).toBeGreaterThan(pageWidth);
  await expect(page.getByTestId('pdf-cell')).toBeVisible();
  await page.getByRole('button', { name: 'Exit full screen' }).click();
  await expect.poll(async () => (await sheet.boundingBox())!.height).toBe(tableHeight);

  await page.getByRole('button', { name: 'Table', exact: true }).click();
  await expect(grid).toBeVisible();
  expect((await sheet.boundingBox())!.height).toBe(tableHeight);
});
