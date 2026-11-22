import { expect, test, type Page } from '@playwright/test';

test('two reviewers assign, mention, receive, open the correct row and reply', async ({
  browser,
  baseURL,
  request,
}) => {
  const project = await (
    await request.post('/api/v1/projects', {
      data: { name: 'Collaboration test' },
    })
  ).json();
  const rows = ['Item;Description;Quantity;Unit;Unit price;Total'];
  for (let i = 1; i <= 60; i++)
    rows.push(`${i};Synthetic pipe ${i};${i + 5};m;13;${(i + 5) * 13 + (i === 43 ? 2400 : 0)}`);
  const upload = await request.post('/api/v1/documents', {
    multipart: {
      file: {
        name: 'team-bill.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from(rows.join('\n')),
      },
    },
  });
  expect(upload.status()).toBe(201);
  const { document, dataset } = await upload.json();
  await request.put(`/api/v1/projects/${project.project_id}/documents`, {
    data: { document_id: document.document_id },
  });
  const validation = await request.post(`/api/v1/datasets/${dataset.dataset_id}/validation-runs`, { data: {} });
  expect(validation.status()).toBe(201);
  const run = await validation.json();
  const findings = await (await request.get(`/api/v1/validation-runs/${run.run_id}/issues?limit=500`)).json();
  const issue = findings.items.find((item: { detector_id: string }) => item.detector_id === 'deterministic.line_total');
  expect(issue).toBeTruthy();
  const contexts = await Promise.all([
    browser.newContext({ baseURL, viewport: { width: 1440, height: 900 } }),
    browser.newContext({ baseURL, viewport: { width: 1440, height: 900 } }),
  ]);
  try {
    const [larissa, johan] = await Promise.all(contexts.map((context) => context.newPage()));
    for (const [page, name] of [
      [larissa, 'Larissa'],
      [johan, 'Johan'],
    ] as const) {
      await page.goto('/workspace');
      // The reviewer is chosen in the user menu; the bell appears once one is.
      await page.getByRole('button', { name: /^Open the user menu/ }).click();
      await page.getByRole('menuitem', { name: 'Choose reviewer…', exact: true }).click();
      await page.getByLabel('Your name', { exact: true }).fill(name);
      await page.getByRole('button', { name: 'Join review', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Notifications, 0 unread', exact: true })).toBeVisible();
    }
    await larissa.goto(
      `/workspace?document=${document.document_id}&run=${run.run_id}&issue=${issue.issue_id}&tab=risks`,
    );
    await expect(larissa.getByRole('heading', { name: "What's wrong", exact: true })).toBeVisible();
    const thread = (page: Page) => page.getByRole('region', { name: 'Finding comments', exact: true });
    const task = (page: Page) => thread(page).getByRole('group', { name: 'Task', exact: true });
    // React Aria selects: a trigger button named by its value and label, opening a listbox.
    const field = (page: Page, label: string) => task(page).getByRole('button', { name: label });
    const choose = async (page: Page, label: string, option: string) => {
      await field(page, label).click();
      await page.getByRole('option', { name: option, exact: true }).click();
    };
    await choose(larissa, 'Assignee', 'Johan');
    await expect(field(larissa, 'Assignee')).toContainText('Johan');
    await choose(larissa, 'Type', 'Check');
    await expect(field(larissa, 'Type')).toContainText('Check');
    await thread(larissa)
      .getByRole('button', { name: /^Comments/ })
      .click();
    await expect(thread(larissa).getByText('assigned Johan', { exact: true })).toBeVisible();
    const composer = thread(larissa).getByRole('textbox', {
      name: 'Comment as Larissa',
    });
    await composer.fill('@jo');
    await expect(thread(larissa).getByRole('list', { name: 'Mention suggestions' })).toBeVisible();
    await composer.press('Enter');
    await expect(composer).toHaveValue('@johan ');
    await composer.press('End');
    await composer.pressSequentially('check this out, the total is too high.');
    await thread(larissa).getByRole('button', { name: 'Send comment' }).click();
    const message = '@johan check this out, the total is too high.';
    await expect(thread(larissa).getByText(message, { exact: true })).toBeVisible();
    // The assignment and the mention both reach Johan; opening one reads both (same finding).
    await expect(
      johan.getByRole('button', {
        name: 'Notifications, 2 unread',
        exact: true,
      }),
    ).toBeVisible();
    await johan.getByRole('button', { name: 'Notifications, 2 unread', exact: true }).click();
    await expect(
      johan
        .getByRole('region', { name: 'Notifications', exact: true })
        .getByRole('button', { name: /Larissa assigned you/ }),
    ).toBeVisible();
    await johan
      .getByRole('region', { name: 'Notifications', exact: true })
      .getByRole('button', { name: /Larissa mentioned you/ })
      .click();
    await expect(johan).toHaveURL(new RegExp(`issue=${issue.issue_id}`));
    await expect(johan.getByRole('heading', { name: 'team-bill.csv', exact: true })).toBeVisible();
    await expect(thread(johan).getByText(message, { exact: true })).toBeVisible();
    const selected = johan.getByRole('gridcell').filter({ hasText: /^3024/ });
    await expect(selected).toHaveClass(/bg-issue-cell-strong/);
    await expect(selected).toBeInViewport();
    await expect(
      johan.getByRole('button', {
        name: 'Notifications, 0 unread',
        exact: true,
      }),
    ).toBeVisible();
    await expect(field(johan, 'Assignee')).toContainText('Johan');
    await expect(field(johan, 'Status')).toHaveCount(0);
    await expect(field(larissa, 'Status')).toHaveCount(0);
    // A historical Done task stays Done when its date is edited in the UI.
    const taskUrl = `/api/v1/collaboration/issues/${issue.issue_id}/task`;
    const readTask = async () => (await (await contexts[1].request.get(
      `/api/v1/collaboration/issues/${issue.issue_id}/comments`,
    )).json()).task;
    const seeded = await contexts[1].request.put(taskUrl, {
      data: { assignee: 'johan', status: 'done', task_type: 'check', due_date: '2000-01-03' },
    });
    expect(seeded.ok()).toBe(true);
    await expect(task(johan).getByRole('spinbutton', { name: /^year/ })).toHaveText('2000');
    await task(johan).getByRole('button', { name: /^Choose due date/ }).click();
    await johan.getByRole('button', { name: /January 15, 2000/ }).click();
    await expect.poll(readTask).toMatchObject({ status: 'done', assignee: 'johan', due_date: '2000-01-15' });
    await expect(task(larissa).getByRole('spinbutton', { name: /^day/ })).toHaveText('15');
    // Johan updating his own task notifies nobody.
    await expect(
      larissa.getByRole('button', {
        name: 'Notifications, 0 unread',
        exact: true,
      }),
    ).toBeVisible();
    await thread(johan)
      .getByRole('textbox', { name: 'Comment as Johan' })
      .fill('@larissa confirmed, I will check the source.');
    await thread(johan).getByRole('button', { name: 'Send comment' }).click();
    await expect(
      thread(larissa).getByText('@larissa confirmed, I will check the source.', { exact: true }),
    ).toBeVisible();
    // The risk list shows the task next to the risk.
    await larissa.getByRole('button', { name: 'All risks' }).click();
    await expect(larissa.getByRole('list', { name: 'Risks' }).getByText('Assigned to Johan')).toBeVisible();
    const risks = larissa.getByRole('list', { name: 'Risks' });
    await expect(risks.getByText('Check', { exact: true })).toBeVisible();
    await expect(risks.getByText(/^(To do|In progress|Waiting|Done)(:|$)/)).toHaveCount(0);
    await expect(risks.getByText(/^Overdue:/)).toBeVisible();
    await larissa.getByRole('button', { name: 'Filters', exact: true }).click();
    await larissa.getByText('Overdue tasks only', { exact: true }).click();
    await expect(larissa.getByRole('checkbox', { name: 'Overdue tasks only' })).toBeChecked();
    await expect(risks.getByRole('button')).toHaveCount(1);
    await expect(risks.getByText(/^Overdue:/)).toBeVisible();
    await larissa.getByText('Overdue tasks only', { exact: true }).click();
    await expect(larissa.getByRole('checkbox', { name: 'Overdue tasks only' })).not.toBeChecked();
    await task(johan).getByRole('button', { name: 'Clear due date', exact: true }).click();
    await expect.poll(readTask).toMatchObject({ status: 'done', assignee: 'johan', due_date: null });
    await expect(risks.getByText(/^Overdue:/)).toHaveCount(0);
    // A copied URL works even without an active-document localStorage entry.
    await johan.evaluate(() => localStorage.clear());
    await johan.reload();
    await expect(thread(johan).getByText(message, { exact: true })).toBeVisible();
    await expect(selected).toBeInViewport();
    // The user menu switches Larissa's browser to Johan, and back.
    const switchTo = async (name: string) => {
      await larissa.getByRole('button', { name: /^Open the user menu/ }).click();
      await larissa.getByRole('menuitemradio', { name, exact: true }).click();
      await expect(larissa.getByRole('menu')).toBeHidden();
    };
    const current = async () => (await (await contexts[0].request.get('/api/v1/collaboration/session')).json()).reviewer.handle;
    await switchTo('Johan');
    await expect.poll(current).toBe('johan');
    await expect(larissa.getByRole('button', { name: 'Notifications, 0 unread', exact: true })).toBeVisible();
    await switchTo('Larissa');
    await expect.poll(current).toBe('larissa');
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});
