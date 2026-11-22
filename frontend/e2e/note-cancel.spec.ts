import { expect, test } from '@playwright/test';
import { billPath } from './environment.ts';
import { openInProject } from './openInProject.ts';
import { translator } from '../src/i18n/messages.ts';

for (const language of ['en', 'de'] as const) {
  test(`cancel a note without saving or changing existing notes (${language})`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await openInProject(page, billPath, 'e2e-bill.xlsx');
    const risks = page.getByRole('list', { name: 'Risks', exact: true });
    await expect(risks.getByRole('button')).toHaveCount(1);
    await risks.getByRole('button').click();
    const run = new URL(page.url()).searchParams.get('run');
    const { items } = await (await page.request.get(`/api/v1/validation-runs/${run}/issues`)).json();
    const issueUrl = `/api/v1/issues/${items[0].issue_id}`;
    const readIssue = async () => (await page.request.get(issueUrl)).json();
    const original = await readIssue();

    if (language === 'de') {
      await page.getByRole('button', { name: /^Open the user menu/ }).click();
      await page.getByRole('menuitem', { name: 'Settings' }).click();
      await page.getByRole('dialog', { name: 'Settings' }).getByText('Deutsch', { exact: true }).click();
      await page.keyboard.press('Escape');
    }
    await expect(page.locator('html')).toHaveAttribute('lang', language);
    const t = translator(language);
    const decision = page.getByRole('group', { name: t('Review decision') });
    const add = decision.getByRole('button', { name: t('Add a note'), exact: true });
    const note = decision.getByRole('textbox', { name: t('Note (optional)') });
    const cancel = decision.getByRole('button', { name: t('Cancel'), exact: true });
    const dialog = page.getByRole('alertdialog', { name: t('Discard unsaved note?') });
    const writes: string[] = [];
    page.on('request', (request) => {
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) writes.push(request.url());
    });

    for (const value of ['', '   ', 'typed then cleared']) {
      await add.click();
      await note.fill(value);
      if (value === 'typed then cleared') await note.fill('');
      await cancel.click();
      await expect(note).toHaveCount(0);
      await expect(dialog).toHaveCount(0);
      await expect(add).toBeFocused();
    }

    await add.click();
    await note.fill('Draft to discard');
    await cancel.click();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText(t('Only this unsaved draft will be discarded. Saved notes and the review decision will stay unchanged.'))).toBeVisible();
    // Check translated labels fit their controls and the existing small dialog.
    for (const button of await dialog.getByRole('button').all()) {
      expect(await button.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
      const box = (await button.boundingBox())!;
      const bounds = (await dialog.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(bounds.x);
      expect(box.x + box.width).toBeLessThanOrEqual(bounds.x + bounds.width + 1);
    }
    await page.screenshot({ path: test.info().outputPath(`note-confirm-${language}.png`), animations: 'disabled' });
    await dialog.getByRole('button', { name: t('Continue editing') }).click();
    await expect(note).toHaveValue('Draft to discard');
    await cancel.click();
    await page.keyboard.press('Escape');
    await expect(note).toHaveValue('Draft to discard');
    await cancel.click();
    await dialog.getByRole('button', { name: t('Discard changes') }).click();
    await expect(note).toHaveCount(0);
    await expect(add).toBeFocused();
    await add.click();
    await expect(note).toHaveValue('');
    expect(writes).toEqual([]);
    expect(await readIssue()).toEqual(original);

    // Use the original save path, then cancel another draft over the saved note.
    await note.fill('Saved note must remain');
    await decision.getByRole('button', { name: t('Needs clarification'), exact: true }).click();
    await expect(decision.getByText('Saved note must remain', { exact: true })).toBeVisible();
    await expect(note).toHaveCount(0);
    const saved = await readIssue();
    expect(saved.issue.reviewer_comment).toBe('Saved note must remain');
    expect(saved.issue.review_status).toBe('needs_more_information');
    expect(saved.history.length).toBeGreaterThan(original.history.length);
    await expect.poll(() => writes.some((url) => url.endsWith('/clarifications'))).toBe(true);
    const writesAfterSave = writes.length;
    await add.click();
    await note.fill('Do not replace saved note');
    await expect(cancel).toBeVisible();
    expect(await cancel.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`note-editor-${language}.png`), animations: 'disabled' });
    await cancel.click();
    await dialog.getByRole('button', { name: t('Discard changes') }).click();
    await expect(decision.getByText('Saved note must remain', { exact: true })).toBeVisible();
    await add.click();
    await expect(note).toHaveValue('');
    expect(writes).toHaveLength(writesAfterSave);
    expect(await readIssue()).toEqual(saved);
    await page.reload();
    await expect(decision.getByText('Saved note must remain', { exact: true })).toBeVisible();
    await add.click();
    await expect(note).toHaveValue('');
  });
}
