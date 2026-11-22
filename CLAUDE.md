# Desvio project rules (tabular-integrity-workbench)

The rules every teammate and every Claude session follows in this repository; read them first.

This file does not repeat the other guides: [`AGENTS.md`](AGENTS.md) (GitHub issues and the
sample dataset), [`README.md`](README.md) (set-up, run and test commands),
[`LICENSES.md`](LICENSES.md) (dependency inventory) and [`docs/`](docs/) (architecture,
decisions, plan). Where existing code breaks a rule below, the rule wins: fix that code when your
task touches it, and do not copy it.

## 1. How to work here

- **Plan first.** Read the code you will change, then state in a few lines what you will do and
  what you will leave alone. Ask the owner when a request leaves a real choice open.
- **Keep changes small.** One purpose per branch and pull request. Do not rename, reformat or
  refactor code the task does not need.
- **Do not over-engineer.** No new abstraction, option, prop, setting or dependency until a
  second real use needs it.
- **Reuse before adding.** Look in `frontend/src/components/`, `src/hooks/`, `src/utils/` and
  `backend/app/services/` first, and extend what is there instead of adding a second way.
- **Run the checks that cover your change** and report what you ran, what passed, what failed
  and what you did not run. CI (`.github/workflows/ci.yml`) runs all of them on a pull request.
  - Frontend, from `frontend/`: `npm run typecheck`, `npx vitest run`, `npm run build`, and
    `npm run test:e2e` (Playwright) when a flow, a layout or a hit area changes.
  - Backend, from `backend/`, each as `.venv/bin/python -m ...`: `pytest -q`, `ruff check .`,
    `ruff format --check .` and `mypy`.
- **Never skip, disable, delete or weaken a failing test**, a type check or the coverage gate to
  get a green run. Fix the code; if the test itself is wrong, fix it and say why.
- **Free and permissive licences only** (MIT, BSD, Apache-2.0, ISC and the like; no GPL, LGPL or
  AGPL, no paid service, no enterprise edition). A new or upgraded package gets its row in
  `LICENSES.md` in the same change.
- **Money is exact.** Backend: Python `Decimal`, never `float` (floats only inside the
  statistics of the signal checks). API: decimals are strings. Frontend: `src/utils/decimal.ts`
  and `src/utils/format.ts`, never `Number` or `parseFloat` on an amount.
- **Nothing invented.** No made-up numbers, no sample data shown as real, no fake progress, no
  placeholder results: show the real value or none. Every control does what its label says; do
  not ship a button, link, filter or menu item that does nothing.
- **Data stays private.** Uploaded bills, `Sample BoQ Dataset/`, `backend/var/` and
  `backend/demo-set/` are never published or sent to an outside service (see `AGENTS.md`), and
  the last two are never committed. The app works without network access: add no analytics,
  telemetry, CDN asset or call to an outside service. Two exceptions, each off without its own
  key: the optional assistant, and the Claude bill review that a reviewer starts for one bill
  (`app/services/bill_reviews.py`). Never commit a secret or a token.

## 2. Clean code

The model is Meta's practice for React and TypeScript, starting with the Rules of React
(<https://react.dev/reference/rules>). The frontend has no linter, so `tsc`, the tests and
review enforce these.

React:

- Components and hooks are pure: the same props, state and context give the same output, with no
  side effect and no mutation of props or state while rendering. Call `t()` while rendering or in
  a handler, never at module load (constant tables mark their text with `msg()`).
- Call hooks only at the top level of a component or of a `use...` hook: never in a condition, a
  loop or a callback.
- Do not store what can be computed, and do not copy props or state into other state through an
  effect. Compute while rendering, as `usePagedRows` in `components/TableCard.tsx` does when it
  keeps the page offset on a page that exists.
- An effect only synchronises with something outside React (a request, a timer, the DOM, a
  subscription) and cleans up after itself. Load data with `useApiResource` and run user actions
  with `useAsyncAction` (`src/hooks/`). API calls live in `src/services/` on top of
  `apiClient.ts`, never in a component.
- Keep state minimal and local; lift it only to the nearest parent that needs it. Context is for
  what the whole app shares (session, workspace, project, language, the overlays).
- Add `useMemo` or `useCallback` only for a measured cost or an identity an effect depends on.

Structure, names and types:

- One component per file, named like the file (`TableCard.tsx`); hooks are `useThing.ts`; logic
  without React goes in a plain module (`projectOverview.ts`) and is tested on its own. Named
  exports only in `src/`.
- Shared parts live in `src/components/` and never import from `src/features/`; a feature's own
  parts stay in `src/features/<feature>/`.
- Small and focused: a function does one thing, a component shows one thing. A component file
  that passes about 300 lines is due for a split; do not grow the ones already past that.
- Names are full words that say what the thing is or does (`pageSize`, `onRowActivate`,
  `isDisabled`): no abbreviations, no `data2`, no `handleStuff`.
- TypeScript is strict. No `any`, `@ts-ignore` or `@ts-expect-error` in application code: take
  `unknown` at a boundary and narrow it (`parseDecimal`, `isLanguage`). API shapes are typed once
  in `services/apiTypes.ts` and change together with the backend model and `docs/api/rest-api.md`.
- Backend: HTTP in `app/api/routes`, use cases in `app/services`, persistence in
  `app/repositories`, models in `app/models`, API shapes in `app/schemas`. `ruff` and strict
  `mypy` pass; a `# type: ignore` or `# noqa` names its code and its reason.

Hygiene:

- No dead code, unused export, commented-out code or leftover `console.log`. Delete it; git
  keeps the history.
- A comment explains why (a constraint, a trade-off, a consequence), not what the next line does.
  An exported component keeps its doc comment true when its behaviour changes.
- One way to do a thing: `cx()` for class names, `Button` and `IconButton` for buttons, `Dialog`
  for modals, `utils/format.ts` for numbers and dates, `utils/safeStorage.ts` for browser
  storage. Do not add a second.

Tests:

- Tests sit next to the code as `*.test.ts(x)` (Vitest, Testing Library); browser flows are
  `frontend/e2e/*.spec.ts` (Playwright); backend tests are in `backend/tests/unit` (laid out
  like `app/`) and `backend/tests/integration`.
- Test behaviour as a person meets it: render with `renderApp` (`src/test/render.tsx`), stub the
  API with `mockFetch` (`src/test/fetchMock.ts`), find elements by role and accessible name or by
  label, and act through `user-event`. Do not assert on class names, internal state or component
  structure; use `data-testid` only where no role or label exists.
- A test that writes to `console.error` fails (`src/test/consoleGuard.ts`): fix the cause.
- A new behaviour or a bug fix comes with a test that fails without the change.

## 3. UI and UX

The first reference is Apple's Human Interface Guidelines
(<https://developer.apple.com/design/human-interface-guidelines/layout>); the second is Material
Design (<https://m1.material.io/>). The owner's rules come first and are not optional:

1. **No text nobody asked for.** Do not add a subtitle, caption, helper line, hint or
   explanation the owner did not request; ask first if you think one is needed. The accessible
   name of a control (`aria-label`, a table's caption) is required and is not extra text.
2. **No server or deployment notices in the app.** Nothing like an info banner saying "Sign-in
   is off on this server ... Set TWB_AUTH__TOKENS to require sign-in." No environment variable,
   port or administrator how-to appears in the interface; configuration belongs in `README.md`
   and `docs/deployment.md`.
3. **No "AI slop" look.** No decorative stat tiles (a big number with a caption under each), no
   gradients, no ornamental cards, no surface nested in a surface. Layouts are plain, aligned
   and quiet, and the data carries the weight.
4. **One table for every list of items:** `TableCard` (`components/TableCard.tsx`, over
   `DataTable`), with its own `loading` and `status` props for the loading, empty and failed
   states, so all tables look and behave the same. No hand-built `<table>`, card grid, or
   separate spinner or empty block for a list. The spreadsheet in `features/workspace/sheet/` is
   a sheet, not a list, and is the exception.
5. **Settings and the profile are overlays** over the current page
   (`features/settings/SettingsDialog.tsx`, `Dialog` with `backdrop="blur"`), never pages.
6. **One primary action per screen:** one `variant="primary"` button; the others are `secondary`
   or `ghost`, destructive ones `danger`.
7. **Colour is never the only signal.** Pair it with an icon, a label or a shape, as `Banner`,
   `StatusBadge` and `SeverityIndicator` do.
8. **Tokens only.** Colour, type, radius, shadow and easing come from `src/styles/index.css`
   through their utilities (`bg-surface`, `text-ink-secondary`, `border-hairline`, `text-body`).
   No raw hex or rgb colour and no arbitrary font size in a component's classes or styles. A new
   token needs light, dark and high-contrast values that meet WCAG AA.
9. **Respect reduced motion.** `index.css` stops animations for the system setting and for the
   app's own (`data-motion='reduce'`); motion driven from JavaScript must check both. Motion
   lasts 150 to 200 ms with `ease-standard` and only explains a change.
10. **Every visible string is in the i18n catalogue, in English and German,** including
    `aria-label`, `title`, placeholders and error texts: `t('English text')` with its German in
    `src/i18n/de/`, or a dotted key with both texts in `src/i18n/messages.ts`. Use
    `{placeholders}`, not concatenation. `src/i18n/catalog.test.ts` fails on a missing German
    text. Values from the backend or an uploaded bill stay as they are.

How the guidelines apply here:

- **Layout.** Everything sits on the 4 px spacing scale, with 24 px page margins (16 px on a
  phone). A page works from phone width to a wide desktop without horizontal page scroll, and at
  every text size offered in Settings (sizes are in rem).
- **Hierarchy.** One `h1` per page, the title in the top bar (`usePageTitle`), then headings in
  order. Size and weight from the five type tokens (`text-title` to `text-caption`) carry the
  hierarchy, not colour, boxes or shadows.
- **Clarity and deference.** The bill and its findings are the content; the frame stays quiet:
  hairline borders, one accent colour (primary action, selection, focus) and shadows only on
  overlays.
- **Consistency.** The same thing looks and behaves the same everywhere. Build from the shared
  components (`Button`, `IconButton`, `Dialog`, `Tabs`, `Select`, `Field`, `Badge`, `Banner`,
  `EmptyState`, `ErrorState`), and change the component, not one use of it.
- **Hit targets.** The guidelines ask for 44 pt; here every control is at least 32 × 32 px with a
  mouse and 48 × 48 px with a coarse pointer, through the constants in `components/hitTarget.ts`.
  `e2e/touch-targets.spec.ts` measures them.
- **Keyboard and focus.** Every action works from the keyboard with a visible focus ring. Build
  interactive parts from React Aria components, as `Button`, `Dialog` and `DataTable` do.
- **States.** A view that loads data handles loading, empty, failed and read-only (the viewer
  role, `can('write')`).

## 4. Git and pull requests

- Work on a branch and open a pull request against `main`; CI is green before it merges.
- Never push to `main`, force-push or otherwise rewrite shared history without the owner's
  explicit go-ahead for that action.
- A commit has one purpose and a message that says what changed and, where it is not obvious,
  why. Commit only what the task changed.
- No model identifiers in commit message bodies, pull request titles and descriptions, or code
  comments.
- The pull request says what changed, why, and which checks ran with what result.
- Issues, assignees and closing an issue follow [`AGENTS.md`](AGENTS.md).
