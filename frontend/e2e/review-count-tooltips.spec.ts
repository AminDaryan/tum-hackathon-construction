import { expect, test, type Page } from '@playwright/test';
import { billPath } from './environment.ts';
import { openInProject } from './openInProject.ts';

const explanations = {
  en: [
    'Unreviewed findings across the bills in the last project validation. Counts all reviewers, regardless of workspace filters.',
    'Unreviewed findings in the selected validation run of this file. Counts all reviewers, regardless of risk list filters.',
    'Risks awaiting clarification, within the current filters and assignee selection. A risk may group several findings.',
  ],
  de: [
    'Noch nicht geprüfte Befunde aller Leistungsverzeichnisse aus der letzten Projektprüfung. Gilt für alle Prüfenden, unabhängig von den Filtern im Arbeitsbereich.',
    'Noch nicht geprüfte Befunde im ausgewählten Prüflauf dieser Datei. Gilt für alle Prüfenden, unabhängig von den Filtern der Risikoliste.',
    'Risiken, die auf Klärung warten, unter Berücksichtigung der aktuellen Filter und Zuständigkeitsauswahl. Ein Risiko kann mehrere Befunde zusammenfassen.',
  ],
};

async function checkTooltip(page: Page, text: string) {
  const trigger = page.getByRole('button', { name: text, exact: true });
  // Establish pointer modality before entering the trigger after navigation.
  await page.mouse.move(0, 0);
  await page.mouse.move(10, 10);
  await trigger.hover();
  const tooltip = page.getByRole('tooltip');
  await expect(tooltip).toHaveText(text);
  const box = (await tooltip.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
  await page.keyboard.press('Escape');
  await expect(tooltip).toHaveCount(0);
  await page.mouse.move(0, 0);
  await trigger.focus();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Shift+Tab');
  await expect(tooltip).toHaveText(text);
  await page.keyboard.press('Escape');
  await expect(tooltip).toHaveCount(0);
}

test('review count explanations in English and German preserve status filtering', async ({ page }) => {
  const projectId = await openInProject(page, billPath, 'e2e-bill.xlsx');
  const workspace = page.url();
  await expect(page.getByRole('button', { name: 'In review 0', exact: true })).toBeVisible();
  expect((await page.request.post(`/api/v1/projects/${projectId}/validation`)).ok()).toBeTruthy();
  await expect.poll(async () => (await (await page.request.get(`/api/v1/projects/${projectId}`)).json()).project.validation.status).toBe('completed');
  for (const lang of ['en', 'de'] as const) {
    await page.evaluate(l => localStorage.setItem('twb.language', l), lang);
    await page.goto(`/projects/${projectId}`);
    const figure = page.locator('dt').filter({ hasText: lang === 'en' ? /^To review$/ : /^Zu prüfen$/ }).locator('..').locator('dd');
    await expect(figure).toHaveText('1');
    await checkTooltip(page, explanations[lang][0]);
    await page.goto(workspace);
    await page.getByRole('tab', { name: lang === 'en' ? /^Risks/ : /^Risiken/ }).click();
    const list = page.getByRole('list', { name: lang === 'en' ? 'Risks' : 'Risiken', exact: true });
    await expect(list.getByRole('button')).toHaveCount(1);
    await checkTooltip(page, explanations[lang][1]);
    await checkTooltip(page, explanations[lang][2]);
    await page.getByRole('button', { name: explanations[lang][2], exact: true }).click();
    await expect(list.getByRole('button')).toHaveCount(1);
    await page.getByRole('button', { name: lang === 'en' ? 'In review 0' : 'In Klärung 0', exact: true }).click();
    await expect(list.getByRole('button')).toHaveCount(0);
    await page.getByRole('button', { name: lang === 'en' ? 'All 1' : 'Alle 1', exact: true }).click();
    await expect(list.getByRole('button')).toHaveCount(1);
    await expect(page.getByText(lang === 'en' ? '1 finding pending review' : '1 Befund nicht durchgesehen', { exact: true })).toBeVisible();
  }
  // A decision still refreshes the run count, risk list and project overview.
  await page.getByRole('list', { name: 'Risiken', exact: true }).getByRole('button').click();
  await page.locator('[data-decision="in_review"]').click();
  await expect(page.getByText(/^In Klärung: wartet auf Rückmeldung/)).toBeVisible();
  await page.getByRole('button', { name: 'Alle Risiken', exact: true }).click();
  await page.getByRole('button', { name: 'In Klärung 1', exact: true }).click();
  await expect(page.getByRole('list', { name: 'Risiken', exact: true }).getByRole('button')).toHaveCount(1);
  await expect(page.getByText('1 Befund nicht durchgesehen', { exact: true })).toHaveCount(0);
  await page.getByRole('link', { name: 'Übersicht', exact: true }).click();
  await expect(page.locator('dt').filter({ hasText: /^Zu prüfen$/ }).locator('..').locator('dd')).toHaveText('0');

});
