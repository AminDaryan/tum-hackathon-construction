/**
 * The main workflow in the workspace, in a real browser against a real backend: upload a bill
 * into a project and open it from there
 * with one planted line-total error (make_bill.py: F4 says 3725.00, 2.5 t x 1,450.00 is
 * 3,625.00), validate it (the Risks tab opens by itself), open the risk and approve it, which
 * opens its cell for editing in the sheet, correct the cell there, validate the edited table
 * again (every registered check runs; there is no way to choose checks), and download the
 * issues CSV under the Risks list.
 * The page itself never scrolls as a whole document: the main area and the panel scroll.
 */
import { readFile } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';
import { billPath } from './environment.ts';
import { openInProject } from './openInProject.ts';

const finished = (issues: number) => new RegExp(`^Validation run finished with ${issues} issues?\\.`);
const RISK = /^Line total 3725(\.00)? does not match/;

/** The number of checks of the open file's newest run, as the server reports them. */
async function checksOfNewestRun(page: Page) {
  const documentId = new URL(page.url()).searchParams.get('document');
  const { dataset } = await (await page.request.get(`/api/v1/documents/${documentId}`)).json();
  const { items } = await (await page.request.get(`/api/v1/datasets/${dataset.dataset_id}/validation-runs`)).json();
  const run = await (await page.request.get(`/api/v1/validation-runs/${items[0].run_id}`)).json();
  return run.detector_reports.length;
}

/** The document never scrolls: one scroller for the page (main), one per panel tab. */
async function expectNoDocumentScroll(page: Page) {
  const { scrollHeight, clientHeight } = await page.evaluate(() => ({
    scrollHeight: document.scrollingElement!.scrollHeight,
    clientHeight: document.scrollingElement!.clientHeight,
  }));
  expect(scrollHeight).toBeLessThanOrEqual(clientHeight + 1);
}

/**
 * The open file fits the window from 1280 px: the main area has nothing to scroll and the
 * sheet reaches down to the main area's bottom padding (24 px).
 */
async function expectFileFitsWindow(page: Page) {
  const main = page.getByRole('main');
  const overflow = await main.evaluate((element) => element.scrollHeight - element.clientHeight);
  expect(overflow).toBeLessThanOrEqual(1);
  // Both are visible, so both have a box.
  const area = (await main.boundingBox())!;
  const sheet = (await page.getByRole('region', { name: 'LV', exact: true }).boundingBox())!;
  const gap = area.y + area.height - (sheet.y + sheet.height);
  expect(gap).toBeGreaterThanOrEqual(20);
  expect(gap).toBeLessThanOrEqual(28);
}

test('upload, validate, review, correct, revalidate and export a bill', async ({ page }) => {
  const grid = page.getByRole('grid', { name: 'Sheet LV' });
  const lineTotal = grid.getByRole('gridcell').filter({ hasText: /^3,?725(\.00)?/ });
  const tab = (name: string) => page.getByRole('tab', { name: new RegExp(`^${name}`) });
  // The outcome is announced to screen readers only; the Risks tab opens with the results.
  const runStatus = (issues: number) => page.getByRole('status').filter({ hasText: finished(issues) });
  const panel = page.getByRole('complementary', { name: 'Side panel' });

  await test.step('upload the bill into a project and open it from there', async () => {
    await openInProject(page, billPath, 'e2e-bill.xlsx');
    await expect(page).toHaveURL(/\/projects\/prj_\w+\/workspace\?document=doc_/);
    await expect(page.getByRole('navigation', { name: 'Project', exact: true }).getByRole('link', { name: 'Workspace' })).toHaveAttribute('aria-current', 'page');
    // "E2E e2e-bill.xlsx / e2e-bill.xlsx": the project's name leads the file's, with no back button.
    const topBar = page.getByRole('banner', { name: 'Top bar' });
    await expect(topBar.getByRole('link', { name: 'E2E e2e-bill.xlsx' })).toBeVisible();
    await expect(topBar.getByRole('button', { name: /^Back/ })).toHaveCount(0);
    await expect(grid.getByRole('columnheader')).toContainText(['Pos.', 'Kurztext', 'Menge', 'Einheit', 'Einheitspreis', 'Gesamtpreis']);
    await expect(lineTotal).toHaveCount(1);
    // The bill has no linked 3D model, so the panel has no tab for one.
    await expect(tab('3D model')).toHaveCount(0);
    await expect(tab('Properties')).toHaveAttribute('aria-selected', 'true');
    await expectNoDocumentScroll(page);
    await expectFileFitsWindow(page);
  });

  await test.step('the table is checked by itself: one open risk, shown in the Risks tab', async () => {
    await expect(page.getByRole('button', { name: 'Validate the table' })).toHaveCount(0);
    await expect(runStatus(1)).toBeAttached();
    await expect(page.getByRole('tab')).toHaveText(['Properties', /^Risks\s*1$/, 'What-if', 'Quantities']);
    // No outcome box and no "Validation of" line above the sheet.
    await expect(page.getByRole('link', { name: 'Show risks' })).toHaveCount(0);
    await expect(page.getByText(/^Validation of /)).toHaveCount(0);
    await expect(tab('Risks')).toHaveAttribute('aria-selected', 'true');
    await expect(panel.getByRole('list', { name: 'Risks' }).getByRole('button')).toHaveCount(1);
    // The overview (next best action, figures, priorities) is on the project page, not here.
    await expect(page.getByRole('region', { name: 'Next best action' })).toHaveCount(0);
    // There is no picker of validation runs above the sheet.
    await expect(page.getByRole('button', { name: /Validation run/ })).toHaveCount(0);
    // The side panel's tab list never scrolls: no scroll bar or arrows beside the tabs.
    await expect(panel.getByRole('tablist')).toHaveCSS('overflow-y', 'visible');
    await expect(panel.getByRole('tablist')).toHaveCSS('overflow-x', 'visible');
    await expectNoDocumentScroll(page);
    await expectFileFitsWindow(page);
  });

  await test.step('switch the panel tabs: the panel keeps its width and nothing scrolls', async () => {
    const width = (await panel.boundingBox())!.width;
    for (const name of ['What-if', 'Quantities', 'Properties', 'Risks']) {
      await tab(name).click();
      await expect(tab(name)).toHaveAttribute('aria-selected', 'true');
      expect((await panel.boundingBox())!.width).toBe(width);
      await expectNoDocumentScroll(page);
      await expectFileFitsWindow(page);
    }
  });

  await test.step('show the table full screen and back', async () => {
    const sheet = page.getByRole('region', { name: 'LV', exact: true });
    const before = (await sheet.boundingBox())!;
    await page.getByRole('button', { name: 'Full screen' }).click();
    await expect(page.getByRole('button', { name: 'Exit full screen' })).toBeVisible();
    const viewport = await page.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight }));
    await expect.poll(async () => (await sheet.boundingBox())?.width).toBe(viewport.width);
    await expect.poll(async () => (await sheet.boundingBox())?.height).toBe(viewport.height);
    await expect(grid).toBeVisible();
    await page.getByRole('button', { name: 'Exit full screen' }).click();
    await expect(page.getByRole('button', { name: 'Full screen' })).toBeVisible();
    await expect.poll(async () => (await sheet.boundingBox())?.width).toBe(before.width);
    await expectNoDocumentScroll(page);
  });

  await test.step('choose Light in Settings on a dark system: the page and its scroll bars are light', async () => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.getByRole('button', { name: /^Open the user menu/ }).click();
    await page.getByRole('menuitem', { name: 'Settings' }).click();
    const settings = page.getByRole('dialog', { name: 'Settings' });
    const choice = settings.getByRole('radiogroup', { name: 'Colour scheme' });
    await choice.getByText('Light', { exact: true }).click();
    const scheme = () => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme);
    await expect.poll(scheme).toBe('light');
    await choice.getByText('System', { exact: true }).click();
    await expect.poll(scheme).toBe('dark');
    await page.keyboard.press('Escape');
    await expect(settings).toHaveCount(0);
    await page.emulateMedia({ colorScheme: 'light' });
  });

  await test.step('open the risk: the cell is ringed and the detail says what is wrong', async () => {
    await panel.getByRole('list', { name: 'Risks' }).getByRole('button').click();

    await expect(lineTotal).toHaveClass(/bg-issue-cell-strong/);
    await expect(panel.getByText(/^Risk 1 of \d+$/)).toBeVisible();
    await expect(panel.getByRole('heading', { name: "What's wrong" })).toBeVisible();
    await expect(panel.getByText(RISK).first()).toBeVisible();
    const decisions = panel.getByRole('group', { name: 'Review decision' });
    await expect(decisions.getByRole('button', { name: /^Approve/ })).toBeVisible();
    await expect(decisions.getByRole('button', { name: /^Reject/ })).toBeVisible();
    await expect(decisions.getByRole('button', { name: 'Needs clarification' })).toBeVisible();
    await expectNoDocumentScroll(page);
  });

  await test.step('approve the risk: the decision is saved and its cell opens for editing', async () => {
    const decisions = panel.getByRole('group', { name: 'Review decision' });
    await decisions.getByRole('button', { name: /^Approve/ }).click();
    await expect(decisions.getByText(/^Approved on /)).toBeVisible();
    await expect(decisions.getByRole('button', { name: 'Undo decision' })).toBeVisible();
    await expect(decisions.getByText('Every risk is reviewed.')).toBeVisible();
    await expect(tab('Risks')).toHaveText(/^Risks\s*0$/);
    await expect(page.getByRole('textbox', { name: 'Edit F4' })).toBeFocused();
  });

  await test.step('correct the line total in the opened cell', async () => {
    const editor = page.getByRole('textbox', { name: 'Edit F4' });
    await editor.fill('3625.00');
    await editor.press('Enter');
    await expect(page.getByRole('status').filter({ hasText: /^Saved F4 as revision 2\./ })).toBeVisible();
    await expect(grid.getByRole('gridcell').filter({ hasText: /^3,?625(\.00)?/ })).toHaveCount(1);
  });

  await test.step('the edit is checked again by itself: every check runs, no finding left', async () => {
    await expect(runStatus(0)).toBeAttached();
    await expect(tab('Risks')).toHaveAttribute('aria-selected', 'true');
    // With no finding left the list shows the record: the bill's one kept reminder (no excavation).
    await expect(tab('Risks')).toHaveText(/^Risks\s*1$/);
    // Every registered check runs (ADR 0010): 38 in the shipped catalogue, the Claude bill review
    // among them (skipped, as no bill was sent to Claude).
    expect(await checksOfNewestRun(page)).toBe(38);
    await expect(page.getByRole('button', { name: 'Choose checks' })).toHaveCount(0);
  });

  await test.step('download the issues CSV under the Risks list', async () => {
    await tab('Risks').click();
    await panel.getByRole('button', { name: 'All risks' }).click();
    const runId = new URL(page.url()).searchParams.get('run');
    expect(runId).toMatch(/^run_/);
    // The folding part slides open: its height changes in a transition.
    const fold = panel.getByRole('button', { name: 'Downloads and earlier validations' });
    const body = page.locator(`[id="${await fold.getAttribute('aria-controls')}"]`);
    await body.evaluate((element) => {
      element.addEventListener('transitionrun', (event) => element.setAttribute('data-moved', (event as TransitionEvent).propertyName));
    });
    await fold.click();
    await expect(body).toHaveAttribute('data-moved', 'height');
    const downloads = panel.getByRole('region', { name: 'Download the results' });
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      downloads.getByRole('button', { name: 'Download issues (CSV)' }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/^e2e-bill \d{4}-\d{2}-\d{2} \d{2}-\d{2} issues\.csv$/);
    await expect(page.getByRole('status').filter({ hasText: `Export downloaded: ${download.suggestedFilename()}` })).toBeVisible();
    const text = (await readFile(await download.path(), 'utf8')).replace(/^\uFEFF/, '').trim();
    const [header, ...records] = text.split(/\r?\n/);
    expect(header.split(',').slice(0, 4)).toEqual(['validation_run_id', 'dataset_id', 'dataset_revision', 'issue_id']);
    expect(records).toHaveLength(0);
  });

  await test.step("go back to the project's files and open the bill again", async () => {
    await page.getByRole('navigation', { name: 'Project', exact: true }).getByRole('link', { name: 'Workspace' }).click();
    await expect(page).toHaveURL(/\/projects\/prj_\w+\/workspace$/);
    await page.getByRole('main').getByRole('region', { name: /^Files/ }).getByRole('row', { name: /e2e-bill\.xlsx/ }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'e2e-bill.xlsx' })).toBeVisible();
    await expect(page).toHaveURL(/\/workspace/);
  });

  await test.step('Follow-ups and Reports fit the window: their tables fill it and nothing scrolls', async () => {
    // The open project's pages, in the bar under the top bar.
    const project = page.getByRole('navigation', { name: 'Project', exact: true });
    const main = page.getByRole('main');
    for (const [link, table] of [
      ['Follow-ups', /^Clarifications/],
      ['Reports', /^Reports/],
    ] as const) {
      await project.getByRole('link', { name: link }).click();
      await expect(page.getByRole('heading', { level: 1, name: link })).toBeVisible();
      await expect(main.getByRole('region', { name: table })).toBeVisible();
      await expect.poll(() => main.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(1);
      await expectNoDocumentScroll(page);
    }
  });
});
