import { expect, test, type APIRequestContext } from '@playwright/test';
import { translator } from '../src/i18n/messages.ts';

test.use({ actionTimeout: 15_000 });

/** Real, synthetic bills and bidder questions: enough rows for a second page at this viewport. */
async function makeProject(request: APIRequestContext) {
  const project = await (await request.post('/api/v1/projects', { data: { name: 'Overview return' } })).json();
  const path = `/api/v1/projects/${project.project_id}`;
  for (const [name, count] of [['many.csv', 24], ['few.csv', 3], ['clean.csv', 0]] as const) {
    const rows = ['Item;Description;Quantity;Unit;Unit price;Total'];
    for (let i = 1; i <= Math.max(1, count); i++) rows.push(`${i};Synthetic pipe ${i};10;m;13;${count ? 140 + i : 130}`);
    const upload = await request.post('/api/v1/documents', {
      multipart: { file: { name, mimeType: 'text/csv', buffer: Buffer.from(rows.join('\n')) } },
    });
    expect(upload.status()).toBe(201);
    const { document } = await upload.json();
    expect((await request.put(`${path}/documents`, { data: { document_id: document.document_id } })).ok()).toBe(true);
  }
  expect((await request.post(`${path}/validation`)).ok()).toBe(true);
  await expect.poll(async () => (await (await request.get(path)).json()).project.validation.status).toBe('completed');
  const { items } = await (await request.get(`${path}/top-issues?limit=100`)).json();
  expect(items.length).toBeGreaterThanOrEqual(24);
  for (const [index, issue] of items.slice(0, 24).entries()) {
    const response = await request.post(`${path}/clarifications/emails`, {
      data: {
        document_id: issue.document_id, risk_id: `question-${index}`, issue_id: issue.issue_id,
        tier: index % 2 ? 'high' : 'low', title: `Question ${String(index + 1).padStart(2, '0')}`,
      },
    });
    expect(response.ok()).toBe(true);
  }
  return project;
}

for (const language of ['en', 'de'] as const) {
  test(`Overview restores page two, its filter and ordering after details (${language})`, async ({ page, request, browser, baseURL }, testInfo) => {
    const project = await makeProject(request);
    const t = translator(language);
    await page.addInitScript((value) => localStorage.setItem('twb.language', value), language);
    const overviewPath = `/projects/${project.project_id}`;
    await page.goto(overviewPath);
    await expect(page.locator('html')).toHaveAttribute('lang', language);
    const followUps = page.getByRole('region', { name: new RegExp(`^${t('project.nav.followUps')}`) });
    const risks = page.getByRole('region', { name: t('Project overview'), exact: true });
    const bills = page.getByRole('region', { name: new RegExp(`^${t('Files')} \\(\\d+\\)$`) });
    const followUpRows = () => followUps.getByRole('row').allTextContents();
    const riskRows = () => risks.getByRole('row').allTextContents();
    const billRows = () => bills.getByRole('row').allTextContents();
    const parentLink = () => page.getByRole('banner', { name: t('shell.topBar') }).getByRole('link', { name: project.name, exact: true });

    await followUps.getByRole('button', { name: t('Next'), exact: true }).click();
    await expect(followUps.getByRole('button', { name: t('Previous'), exact: true })).toBeEnabled();
    const pageTwo = await followUpRows();
    const followUpRange = await followUps.getByRole('navigation').textContent();
    expect(pageTwo[1]).toContain(t('Bidder question'));
    await followUps.getByRole('row').nth(1).click();
    await expect(page.getByRole('heading', { name: t("What's wrong"), exact: true })).toBeVisible();
    const detailUrl = page.url();
    await parentLink().click();
    await expect(page).toHaveURL(overviewPath);
    await expect.poll(followUpRows).toEqual(pageTwo);
    await expect(followUps.getByRole('navigation')).toHaveText(followUpRange!);

    // Overview offers file filters; the lists' order is fixed, with no sort selector.
    await bills.getByRole('searchbox', { name: t('Search files') }).fill('.csv');
    await bills.getByRole('button', { name: new RegExp(`${t('Type')}$`) }).click();
    await page.getByRole('option', { name: t('Bills'), exact: true }).click();
    await bills.getByRole('button', { name: new RegExp(`${t('State')}$`) }).click();
    await page.getByRole('option', { name: t('Findings to review'), exact: true }).click();
    await expect(bills.getByRole('row')).toHaveCount(3);
    await expect(bills.getByText('clean.csv', { exact: true })).toHaveCount(0);
    await risks.getByRole('button', { name: t('Next'), exact: true }).click();
    await expect(risks.getByRole('button', { name: t('Previous'), exact: true })).toBeEnabled();
    const riskPageTwo = await riskRows();
    const filteredBills = await billRows();
    const riskRange = await risks.getByRole('navigation').textContent();
    const boxes = await Promise.all([risks, followUps, bills].map((box) => box.boundingBox()));
    await page.screenshot({ path: testInfo.outputPath('before-detail.png'), fullPage: true });
    await followUps.getByRole('row').nth(1).click();
    await expect(page.getByRole('heading', { name: t("What's wrong"), exact: true })).toBeVisible();
    await parentLink().click();
    await expect(bills.getByRole('button', { name: new RegExp(`${t('State')}$`) })).toContainText(t('Findings to review'));
    await expect(bills.getByRole('searchbox', { name: t('Search files') })).toHaveValue('.csv');
    await expect(bills.getByRole('button', { name: new RegExp(`${t('Type')}$`) })).toContainText(t('Bills'));
    await expect.poll(followUpRows).toEqual(pageTwo);
    await expect.poll(riskRows).toEqual(riskPageTwo);
    await expect.poll(billRows).toEqual(filteredBills);
    await expect(risks.getByRole('navigation')).toHaveText(riskRange!);
    // Align the existing main scroller before comparing layout; scroll restoration is separate.
    await page.getByRole('main').evaluate((main) => { main.scrollTop = 0; });
    await page.screenshot({ path: testInfo.outputPath('after-detail.png'), fullPage: true });
    const afterBoxes = await Promise.all([risks, followUps, bills].map((box) => box.boundingBox()));
    for (let i = 0; i < boxes.length; i++) {
      expect(afterBoxes[i]?.width).toBe(boxes[i]?.width);
      expect(afterBoxes[i]?.height).toBe(boxes[i]?.height);
    }
    // The risk entry also keeps its second page; the existing Overview tab still returns there.
    await risks.getByRole('row').nth(1).click();
    await expect(page.getByRole('heading', { name: t("What's wrong"), exact: true })).toBeVisible();
    await page.getByRole('navigation', { name: t('project.nav.label'), exact: true }).getByRole('link', { name: t('project.nav.overview'), exact: true }).click();
    await expect.poll(riskRows).toEqual(riskPageTwo);

    // A fresh browser with no preceding list page can still return via the project breadcrumb.
    const directContext = await browser.newContext({ baseURL, viewport: { width: 1440, height: 900 } });
    try {
      await directContext.addInitScript((value) => localStorage.setItem('twb.language', value), language);
      const direct = await directContext.newPage();
      await direct.goto(detailUrl);
      await expect(direct.getByRole('heading', { name: t("What's wrong"), exact: true })).toBeVisible();
      await direct.getByRole('banner', { name: t('shell.topBar') }).getByRole('link', { name: project.name, exact: true }).click();
      await expect(direct).toHaveURL(overviewPath);
      await expect(direct.getByRole('region', { name: new RegExp(`^${t('project.nav.followUps')}`) }).getByRole('button', { name: t('Previous'), exact: true })).toBeDisabled();
    } finally {
      await directContext.close();
    }
  });
}
