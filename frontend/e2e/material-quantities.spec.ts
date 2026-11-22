import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import { openInProject } from './openInProject.ts';

test('bill quantities retain specs and sources in supplier drafts and CSV', async ({ page }) => {
  await openInProject(page, {
    name: 'fictitious-materials.csv', mimeType: 'text/csv',
    buffer: Buffer.from([
      'Position,Description,Quantity,Unit,Unit price,Total',
      '01,Concrete C25/30 XC2,12.25,m³,100,1225',
      '02,Concrete C25/30 XC2,7.5,m³,110,825',
      '03,Concrete C30/37 XC2,8,m³,120,960',
      '04,DN150 pipe,31,m,20,620',
      '05,DN150 pipe,14.5,m,21,304.5',
      '06,DN100 pipe,6,m,18,108',
      '07,Concrete C25/30 XC2,2,m²,30,60',
      '08,Concrete C25/30 - XC2,1.25,m³,100,125',
    ].join('\n')),
  }, 'fictitious-materials.csv');
  await page.getByRole('tab', { name: 'Quantities', exact: true }).click();
  const panel = page.getByRole('tabpanel');
  await expect(panel.getByRole('status')).toContainText('6 groups. 0 positions omitted.');
  await expect(panel.getByRole('checkbox')).toHaveCount(6);
  const concrete = panel.getByRole('checkbox', { name: 'Concrete C25/30 XC2 19.75 m³', exact: true });
  const pipe = panel.getByRole('checkbox', { name: 'DN150 pipe 45.5 m', exact: true });
  await expect(concrete).toBeVisible();
  await expect(pipe).toBeVisible();
  await panel.getByRole('button', { name: 'Contributing positions (2)' }).first().click();
  await expect(panel.getByRole('button', { name: /position 01, row 2/ })).toBeVisible();
  await expect(panel.getByRole('button', { name: /position 02, row 3/ })).toBeVisible();
  await concrete.locator('xpath=ancestor::label').click();
  await expect(concrete).toBeChecked();
  await pipe.locator('xpath=ancestor::label').click();
  await expect(panel.getByRole('button', { name: 'Confirm same spec and merge' })).toBeDisabled();
  await pipe.locator('xpath=ancestor::label').click();
  await panel.getByRole('button', { name: 'Request supplier prices' }).click();
  const dialog = page.getByRole('dialog', { name: 'Supplier price request' });
  await expect(dialog.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue(/19.75 m³/);
  await expect(dialog.getByRole('textbox', { name: 'Message', exact: true })).not.toHaveValue(/DN150/);
  await page.keyboard.press('Escape');
  const downloadPromise = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'Export quantities as CSV' }).click();
  const download = await downloadPromise;
  const csv = await readFile(await download.path(), 'utf8');
  expect(csv).toContain('"Concrete C25/30 XC2","19.75","m³"');
  expect(csv).toContain('01 / 2 / 12.25 m³');
  expect(csv).not.toContain('DN150');
  await panel.getByRole('checkbox', { name: 'Concrete C25/30 - XC2 1.25 m³', exact: true }).locator('xpath=ancestor::label').click();
  await panel.getByRole('button', { name: 'Confirm same spec and merge' }).click();
  await expect(panel.getByRole('status')).toContainText('5 groups');
  await expect(panel.getByRole('checkbox', { name: 'Concrete C25/30 XC2 21.00 m³', exact: true })).toBeVisible();
  await expect(panel.getByText('Merged by reviewer')).toBeVisible();
  await panel.getByRole('button', { name: 'Reset merges' }).click();
  await expect(concrete).toBeVisible();
  await expect(panel.getByRole('status')).toContainText('6 groups');
  await page.getByRole('gridcell', { name: '12.25', exact: true }).dblclick();
  const editor = page.getByRole('textbox', { name: 'Edit C2' });
  await editor.fill('13.25');
  await editor.press('Enter');
  await expect(panel.getByRole('checkbox', { name: 'Concrete C25/30 XC2 20.75 m³', exact: true })).toBeVisible();
});
