/**
 * The frame: the top bar spans the window, the navigation opens over the page from the menu
 * button without moving it, and the pages of an open project are in a bar right under the top
 * bar.
 */
import { expect, test, type Page } from '@playwright/test';

/** The box of the main area in each of the next 30 frames (about half a second), as "left,width". */
function recordMainBox(page: Page) {
  return page.evaluate(
    () =>
      new Promise<string[]>((resolve) => {
        const boxes: string[] = [];
        const record = () => {
          const box = document.getElementById('main-content')?.getBoundingClientRect();
          boxes.push(box ? `${box.left},${box.width}` : 'none');
          if (boxes.length < 30) requestAnimationFrame(record);
          else resolve(boxes);
        };
        requestAnimationFrame(record);
      }),
  );
}

test('the navigation opens over the page, and a project shows its pages in a bar under the top bar', async ({ page }) => {
  const project = await (await page.request.post('/api/v1/projects', { data: { name: 'E2E navigation' } })).json();
  await page.goto('/projects');
  await expect(page.getByRole('row', { name: /E2E navigation/ })).toBeVisible();
  const width = page.viewportSize()!.width;
  const topBar = page.getByRole('banner', { name: 'Top bar' });
  expect(await topBar.boundingBox()).toMatchObject({ x: 0, y: 0, width, height: 56 });
  await expect(topBar.getByText('Desvio', { exact: true })).toBeVisible();
  // The page takes the whole width under it.
  expect(await page.getByRole('main').boundingBox()).toMatchObject({ x: 0, y: 56, width });
  await expect(page.getByRole('navigation', { name: 'Project', exact: true })).toHaveCount(0);

  // The navigation slides in over the page, which stays where it is in every frame.
  const opening = recordMainBox(page);
  await page.getByRole('button', { name: 'Open the navigation' }).click();
  const navigation = page.getByRole('navigation', { name: 'Primary' });
  await expect(navigation.getByRole('link', { name: 'Users' })).toBeVisible();
  expect(new Set(await opening)).toEqual(new Set([`0,${width}`]));
  // Once it has slid in, its menu button is where the top bar's is.
  const menuButtonLeft = (await page.getByRole('button', { name: 'Open the navigation', includeHidden: true }).boundingBox())!.x;
  await expect.poll(async () => (await page.getByRole('button', { name: 'Close the navigation' }).boundingBox())!.x).toBe(menuButtonLeft);

  // Going to a project closes it; the project's pages are in the bar right under the top bar.
  await navigation.getByRole('link', { name: 'E2E navigation' }).click();
  await expect(page).toHaveURL(`/projects/${project.project_id}`);
  await expect(navigation).toHaveCount(0);
  const projectBar = page.getByRole('navigation', { name: 'Project', exact: true });
  await expect(projectBar.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
  const bar = projectBar.locator('xpath=..');
  // The top bar names the project; the bar under it starts with Overview, without the name.
  await expect(bar.getByText('E2E navigation', { exact: true })).toHaveCount(0);
  await expect(bar).toHaveText(/^Overview/);
  expect(await bar.boundingBox()).toMatchObject({ x: 0, y: 56, width, height: 49 });
  expect(await page.getByRole('main').boundingBox()).toMatchObject({ x: 0, y: 105, width });

  await projectBar.getByRole('link', { name: 'Follow-ups' }).click();
  await expect(page).toHaveURL(`/projects/${project.project_id}/follow-ups`);
  await expect(projectBar.getByRole('link', { name: 'Follow-ups' })).toHaveAttribute('aria-current', 'page');
  // The page is as tall as the window under the two bars, so the main area has nothing to scroll.
  await expect(page.getByRole('heading', { name: 'Follow-ups', level: 1 })).toBeVisible();
  await expect.poll(() => page.getByRole('main').evaluate((main) => main.scrollHeight - main.clientHeight)).toBe(0);

  // The navigation marks the open project among the projects.
  await page.getByRole('button', { name: 'Open the navigation' }).click();
  await expect(navigation.getByRole('link', { name: 'E2E navigation' })).toHaveAttribute('aria-current', 'page');
  await page.keyboard.press('Escape');
  await expect(navigation).toHaveCount(0);
});
