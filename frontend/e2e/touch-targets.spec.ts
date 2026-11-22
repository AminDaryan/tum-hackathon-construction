/**
 * Hit areas of the workspace in the built interface: the navigation and its menu button, the sheet's toolbar and
 * paging buttons, the side panel's tabs and divider, the risk cards, the Risks list with its
 * filters, the cell note, the risk detail's decision buttons, the project's navigation and the
 * project page the bill was opened from are measured in Chromium, with a fine
 * pointer (at least 32 × 32 CSS px) and with a coarse one (at least 48 × 48, Tailwind's
 * `pointer-coarse:` variant).
 *
 * Each clickable control must also show the pointing hand (`not-allowed` while disabled).
 *
 * Each control's bounding box is read with getBoundingClientRect, after scrolling it to the
 * middle of the viewport. A checkbox counts with the label that wraps it, since a click anywhere
 * on that label switches it. document.elementFromPoint at the middle of each edge and at the
 * centre must return the control (or something inside it), so the box is really where the
 * control is hit and no neighbour or sticky element covers it.
 *
 * Coarse-pointer emulation, as found with the Playwright Chromium this suite runs: touch
 * emulation makes `(pointer: coarse)` and `(hover: none)` match, both as Playwright's `hasTouch`
 * context option and as the CDP command Emulation.setTouchEmulationEnabled, which is used here
 * so the same page is measured twice. Emulation.setEmulatedMedia accepts a `pointer` feature but
 * leaves `(pointer: coarse)` false, so it is not used. The test checks that the media query
 * matches before it measures.
 *
 * The bill is a CSV of 130 items written here (more than one sheet page of 100 rows, so the
 * paging buttons show), with two wrong line totals (two risks to review, so "Next risk" shows).
 */
import { expect, test } from '@playwright/test';
import { openInProject } from './openInProject.ts';
import type { CDPSession, Locator, Page } from '@playwright/test';

const FINE_POINTER_MINIMUM = 32;
const COARSE_POINTER_MINIMUM = 48;
const CONTROLS = 'button, input:not([type="file"]), select, textarea, a[href], summary';
const WRONG_TOTALS = new Set([3, 7]);

function longBill() {
  const lines = ['Pos.,Kurztext,Menge,Einheit,Einheitspreis,Gesamtpreis'];
  for (let item = 1; item <= 130; item += 1) {
    const total = item * 10 + (WRONG_TOTALS.has(item) ? 5 : 0);
    lines.push(`01.${String(item * 10).padStart(4, '0')},Position ${item},${item},m2,10.00,${total}.00`);
  }
  return { name: 'e2e-long-bill.csv', mimeType: 'text/csv', buffer: Buffer.from(`${lines.join('\n')}\n`) };
}

interface Measured {
  control: string;
  width: number;
  height: number;
  hit: boolean;
  cursor: string | null;
  expectedCursor: string | null;
}

function measure(controls: Locator): Promise<Measured[]> {
  return controls.evaluateAll((elements: HTMLElement[]) =>
    elements
      .filter((element) => element.checkVisibility())
      .map((element) => {
        const toggle = element instanceof HTMLInputElement && ['checkbox', 'radio'].includes(element.type);
        const target = (toggle && element.closest('label')) || element;
        target.scrollIntoView({ block: 'center', inline: 'center' });
        const box = target.getBoundingClientRect();
        const middleX = box.left + box.width / 2;
        const middleY = box.top + box.height / 2;
        const probes = [
          [middleX, box.top + 1],
          [middleX, box.bottom - 1],
          [box.left + 1, middleY],
          [box.right - 1, middleY],
          [middleX, middleY],
        ];
        const hit = probes.every(([x, y]) => {
          const found = document.elementFromPoint(x, y);
          return found !== null && target.contains(found);
        });
        const name =
          element.getAttribute('aria-label') ||
          ((element as HTMLInputElement).labels?.[0]?.textContent ?? '').trim() ||
          (element.textContent ?? '').trim() ||
          element.getAttribute('name') ||
          '';
        // Clickable controls show the pointing hand, or "not allowed" while disabled.
        const clickable = toggle || ['BUTTON', 'A', 'SUMMARY'].includes(element.tagName) || element.getAttribute('role') === 'tab';
        const disabled = (element as HTMLButtonElement).disabled || element.getAttribute('aria-disabled') === 'true' || element.hasAttribute('data-disabled');
        return {
          control: `${element.tagName.toLowerCase()}${toggle ? `[${element.type}]` : ''} "${name.slice(0, 60)}"`,
          width: box.width,
          height: box.height,
          hit,
          cursor: clickable ? getComputedStyle(target).cursor : null,
          expectedCursor: clickable ? (disabled ? 'not-allowed' : 'pointer') : null,
        };
      }),
  );
}

async function expectHitAreas(controls: Locator, minimum: number) {
  const measured = await measure(controls);
  expect(measured.length).toBeGreaterThan(0);
  const failing = measured.filter(({ width, height, hit }) => width < minimum || height < minimum || !hit);
  expect(failing, `controls smaller than ${minimum} × ${minimum} px, or not hit across their box`).toEqual([]);
  const wrongCursor = measured.filter(({ cursor, expectedCursor }) => cursor !== expectedCursor);
  expect(wrongCursor, 'clickable controls without the pointer cursor').toEqual([]);
  return measured.map(({ control, width, height, hit }) => ({ control, width, height, hit }));
}

/** Switches Chromium's touch emulation, which decides `(pointer: coarse)`. */
async function emulateCoarsePointer(page: Page, session: CDPSession, enabled: boolean) {
  await session.send('Emulation.setTouchEmulationEnabled', enabled ? { enabled, maxTouchPoints: 1 } : { enabled });
  await expect.poll(() => page.evaluate(() => window.matchMedia('(pointer: coarse)').matches)).toBe(enabled);
}

/** Measures `controls` with a fine pointer, then with a coarse one. */
async function expectHitAreasForBothPointers(page: Page, session: CDPSession, controls: Locator) {
  const fine = await expectHitAreas(controls, FINE_POINTER_MINIMUM);
  await emulateCoarsePointer(page, session, true);
  const coarse = await expectHitAreas(controls, COARSE_POINTER_MINIMUM);
  await emulateCoarsePointer(page, session, false);
  expect(coarse.map(({ control }) => control)).toEqual(fine.map(({ control }) => control));
}

test('the workspace controls have 32 px hit areas, 48 px on coarse pointers', async ({ page }) => {
  const session = await page.context().newCDPSession(page);
  const main = page.getByRole('main');
  const measureBoth = (controls: Locator) => expectHitAreasForBothPointers(page, session, controls);

  await test.step('measure the menu button and the navigation it opens', async () => {
    await page.goto('/projects');
    await expect(page.getByRole('heading', { level: 1, name: 'Projects' })).toBeVisible();
    await measureBoth(page.getByRole('button', { name: 'Open the navigation' }));
    await page.getByRole('button', { name: 'Open the navigation' }).click();
    const navigation = page.getByRole('navigation', { name: 'Primary' });
    await expect(navigation.getByRole('link', { name: 'Users' })).toBeVisible();
    // Measured once it has slid in from the left edge.
    await expect.poll(async () => (await navigation.boundingBox())!.x).toBe(0);
    await measureBoth(navigation.getByRole('link'));
    // The + in the rows of Projects and Users, and the button that closes the navigation.
    await measureBoth(navigation.getByRole('button'));
    await measureBoth(page.getByRole('button', { name: 'Close the navigation' }));
    await page.keyboard.press('Escape');
    await expect(navigation).toHaveCount(0);
  });

  await test.step('upload the bill into a project, open it and measure the sheet toolbar and paging buttons', async () => {
    await openInProject(page, longBill(), 'e2e-long-bill.csv');
    // The region of the sheet is named after its table; a CSV has one table, named after the file.
    const name = await page.getByRole('main').getByRole('heading', { level: 2 }).first().textContent();
    const region = page.getByRole('region', { name: name ?? '', exact: true });
    const pages = region.getByRole('navigation', { name: 'rows pages' });
    await expect(pages.getByRole('button', { name: 'Next' })).toBeVisible();
    // The project's name before the file's in the top bar, a link to the project.
    await measureBoth(page.getByRole('banner', { name: 'Top bar' }).getByRole('link', { name: 'E2E e2e-long-bill.csv' }));
    // The project's pages, in the bar under the top bar.
    await measureBoth(page.getByRole('navigation', { name: 'Project', exact: true }).getByRole('link'));
    await measureBoth(pages.getByRole('button'));
    await pages.getByRole('button', { name: 'Next' }).click();
    await expect(pages).toContainText('101–130 of 130 rows');
    await measureBoth(pages.getByRole('button'));
    await pages.getByRole('button', { name: 'Previous' }).click();
    await expect(pages).toContainText('1–100 of 130 rows');
  });

  await test.step('once the table is checked by itself, measure the panel tabs and the divider', async () => {
    await expect(page.getByRole('status').filter({ hasText: /^Validation run finished with 2 issues\./ })).toBeAttached();
    // The count on the Risks tab arrives with the findings and the report; measure once it is there.
    await expect(page.getByRole('tab', { name: /^Risks/ })).toHaveText(/^Risks\s*2$/);
    await measureBoth(page.getByRole('tab'));
    // The arrow that hides the panel sits over the divider's middle: measure the divider without it.
    const hide = page.getByRole('button', { name: 'Hide the side panel' });
    const arrow = await hide.elementHandle();
    await arrow.evaluate((element) => (element.style.visibility = 'hidden'));
    await measureBoth(page.getByRole('separator', { name: 'Width of the side panel' }));
    await arrow.evaluate((element) => (element.style.visibility = ''));
    await measureBoth(hide);
  });

  await test.step('measure the Risks list: search, status chips, filters and rows', async () => {
    await expect(page.getByRole('tab', { name: /^Risks/ })).toHaveAttribute('aria-selected', 'true');
    const panel = page.getByRole('complementary', { name: 'Side panel' });
    await expect(panel.getByRole('list', { name: 'Risks' }).getByRole('button')).toHaveCount(2);
    await measureBoth(panel.getByRole('searchbox'));
    await measureBoth(panel.getByRole('group', { name: 'Status' }).getByRole('button'));
    await measureBoth(panel.locator('button[aria-haspopup="listbox"]'));
    await measureBoth(panel.getByRole('list', { name: 'Risks' }).getByRole('button'));
  });

  await test.step('open a risk and measure the risk detail', async () => {
    const panel = page.getByRole('complementary', { name: 'Side panel' });
    await panel.getByRole('list', { name: 'Risks' }).getByRole('button').first().click();
    await expect(panel.getByRole('button', { name: 'Details and evidence' })).toBeVisible();
    await measureBoth(panel.getByRole('button', { name: /^(Details and evidence|Price of this position)$/ }));

    const decisions = panel.getByRole('group', { name: 'Review decision' });
    await expect(decisions.getByRole('button', { name: /^Approve/ })).toBeVisible();
    await measureBoth(decisions.getByRole('button'));
    await measureBoth(panel.getByRole('button', { name: /^(All risks|(Previous|Next) risk in the list)$/ }));

    await decisions.getByRole('button', { name: /^Approve/ }).click();
    await expect(decisions.getByRole('button', { name: 'Next risk' })).toBeVisible();
    await page.keyboard.press('Escape');
    await measureBoth(decisions.getByRole('button'));
  });

  await test.step('measure the project page: the overview actions, the files with Validate project, and Add files', async () => {
    await page.getByRole('navigation', { name: 'Project', exact: true }).getByRole('link', { name: 'Overview' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible();
    const files = main.getByRole('region', { name: /^Files/ });
    await expect(files.getByRole('row', { name: /e2e-long-bill\.csv/ })).toBeVisible();
    // The overview's top right: Edit and the project's status.
    const overview = main.getByRole('region', { name: 'Project overview' });
    await measureBoth(overview.getByRole('link', { name: 'Edit' }));
    await measureBoth(overview.getByRole('button', { name: /Status$/ }));
    // The files table, its search and filters, its pages and Validate project at its top right.
    await expect(files.getByRole('button', { name: 'Validate project' })).toBeVisible();
    await measureBoth(files.getByRole('button'));
    // The top bar: back to all projects and the user menu.
    await measureBoth(page.getByRole('banner').getByRole('button'));
    // Its file input is visually hidden; the Choose files… button (and a click on the box) opens it.
    await measureBoth(main.getByRole('region', { name: 'Add files' }).locator('button'));
  });
});
