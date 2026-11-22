/**
 * Files are opened from their project: makes a project, adds `file` through its upload box
 * (a path, or a Playwright file payload) and opens it from the project's Files table, which
 * shows it in the workspace.
 */
import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';

/**
 * @param fileName the name the file is listed under
 * @returns the project's id
 */
export async function openInProject(
  page: Page,
  file: string | { name: string; mimeType: string; buffer: Buffer },
  fileName: string,
): Promise<string> {
  const project = await (await page.request.post('/api/v1/projects', { data: { name: `E2E ${fileName}` } })).json();
  await page.goto(`/projects/${project.project_id}`);
  const addFiles = page.getByRole('region', { name: 'Add files' });
  // The box takes files once the project has loaded.
  await expect(addFiles.getByRole('button', { name: 'Add files…' })).toBeEnabled();
  await addFiles.getByLabel('Choose files to upload').setInputFiles(file);
  const row = page.getByRole('main').getByRole('region', { name: /^Files/ }).getByRole('row', { name: new RegExp(fileName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.click();
  await expect(page.getByRole('heading', { level: 1, name: fileName })).toBeVisible();
  return project.project_id;
}
