import { expect, test } from '@playwright/test';
import { openInProject } from './openInProject.ts';

for (const language of ['en', 'de']) {
  test(`material clear preserves selection and one checkbox per position (${language})`, async ({ page }) => {
    await openInProject(page, {
      name: 'material-filter.csv', mimeType: 'text/csv',
      buffer: Buffer.from('Position,Description,Quantity,Unit,Unit price,Total\n01,Steel S355,2,t,10,20\n02,Steel S355,2,t,20,40\n03,Concrete,2,t,5,10'),
    }, 'material-filter.csv');
    if (language === 'de') {
      await page.evaluate(() => localStorage.setItem('twb.language', 'de'));
      await page.reload();
    }
    await page.getByRole('tab', { name: language === 'en' ? 'What-if' : 'Was wäre wenn', exact: true }).click();
    const panel = page.getByRole('tabpanel');
    const picker = panel.getByRole('combobox');
    const positions = panel.getByRole('list', { name: language === 'en' ? 'Positions' : 'Positionen', exact: true });
    await expect(positions.getByRole('checkbox')).toHaveCount(3);
    await picker.click();
    await page.getByRole('option', { name: /^Steel S355/ }).click();
    await expect(positions.getByRole('checkbox')).toHaveCount(2);
    const clear = panel.getByRole('button', { name: language === 'en' ? 'Clear material or specification' : 'Material oder Spezifikation zurücksetzen' });
    await clear.hover();
    await expect(page.getByRole('tooltip')).toHaveText(language === 'en' ? 'Clear material or specification' : 'Material oder Spezifikation zurücksetzen');
    const box = await clear.boundingBox();
    const inputBox = await picker.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(inputBox!.x + inputBox!.width);
    expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await page.screenshot({ path: `/tmp/material-filter-${language}-clear.png` });
    await clear.click();
    await expect(picker).toHaveValue('');
    await expect(positions.getByRole('checkbox')).toHaveCount(3);
    await expect(positions.getByRole('checkbox').nth(0)).toBeChecked();
    await expect(positions.getByRole('checkbox').nth(1)).toBeChecked();
    const count = language === 'en' ? '2 positions selected' : '2 Positionen ausgewählt';
    await expect(panel.getByText(count, { exact: true })).toBeVisible();
    await positions.getByRole('checkbox').nth(1).locator('xpath=ancestor::label').click();
    await expect(positions.getByRole('checkbox').nth(1)).not.toBeChecked();
    await expect(panel.getByText(language === 'en' ? '1 position selected' : '1 Position ausgewählt', { exact: true })).toBeVisible();
    await positions.getByRole('checkbox').nth(1).locator('xpath=ancestor::label').click();
    await expect(panel.getByText(count, { exact: true })).toBeVisible();
    for (const row of await positions.getByRole('listitem').all()) await expect(row.getByRole('checkbox')).toHaveCount(1);
    await page.screenshot({ path: `/tmp/material-filter-${language}.png` });
    await panel.getByRole('button', { name: language === 'en' ? 'Add price rule' : 'Preisregel hinzufügen' }).click();
    await expect(positions.getByRole('checkbox')).toHaveCount(3);
    await positions.getByRole('checkbox').nth(0).locator('xpath=ancestor::label').click();
    await expect(positions.getByRole('checkbox').nth(0)).not.toBeChecked();
    await positions.getByRole('checkbox').nth(0).locator('xpath=ancestor::label').click();
    await expect(positions.getByRole('checkbox').nth(0)).toBeChecked();
  });
}
