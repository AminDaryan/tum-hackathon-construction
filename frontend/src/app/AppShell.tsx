import { useEffect, useRef } from 'react';
import { Outlet, useLocation, useMatch } from 'react-router-dom';
import { ProjectProvider } from '../features/projects/ProjectContext.tsx';
import { SettingsDialogProvider } from '../features/settings/SettingsDialog.tsx';
import { AppErrorBoundary } from './AppErrorBoundary.tsx';
import { useI18n } from '../i18n/useI18n.ts';
import { OpenProjectNav } from './OpenProjectNav.tsx';
import { TopBar } from './TopBar.tsx';
import { PageTitleProvider } from './pageTitle.tsx';
import { ProjectOutlet } from './ProjectOutlet.tsx';
import { fadeIn } from '../utils/motion.ts';

/**
 * Application frame: skip link, the top bar across the window (the menu button that opens the
 * navigation over the page, the mark, the page's title, notifications and the user menu), on the
 * pages of one project the bar with the project's pages under it, and then the scrolling main
 * area with 24px page margins. The pages of one project share the project, loaded once. When the top-level section changes, the main area
 * scrolls to the top and receives focus so screen-reader and keyboard users start at the new
 * page, unless a dialog over it has the focus. A new page fades in. When the language changes,
 * the page is drawn again in it (pages translate with the module-level `t`); its data stays
 * loaded in the providers.
 */
export function AppShell() {
  const { language, t } = useI18n();
  const mainRef = useRef<HTMLElement>(null);
  const location = useLocation();
  const section = location.pathname.split('/')[1] ?? '';
  const previousSection = useRef(section);
  const pageRef = useRef<HTMLDivElement>(null);
  const previousPath = useRef(location.pathname);
  const projectMatch = useMatch('/projects/:projectId/*');
  const projectId = projectMatch && projectMatch.params.projectId !== 'new' ? (projectMatch.params.projectId ?? null) : null;

  useEffect(() => {
    if (previousSection.current === section) return;
    previousSection.current = section;
    const main = mainRef.current;
    if (!main) return;
    main.scrollTop = 0;
    // A dialog open over the new page (Settings or the profile from a link) keeps the focus: the
    // person may already be typing in it.
    if (!document.activeElement?.closest('[role="dialog"]')) main.focus({ preventScroll: true });
  }, [section]);

  // Another page (not another file or tab of the same page, which live in the query string).
  useEffect(() => {
    if (previousPath.current === location.pathname) return;
    previousPath.current = location.pathname;
    fadeIn(pageRef.current);
  }, [location.pathname]);

  const content = (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col print:block">
      <div className="contents print:hidden">
        <TopBar />
        {projectId && <OpenProjectNav />}
      </div>
      <main id="main-content" ref={mainRef} tabIndex={-1} className="relative min-h-0 min-w-0 flex-1 overflow-y-auto outline-none print:overflow-visible">
        <div key={language} ref={pageRef} className="w-full px-6 py-6 max-sm:px-4 print:p-0">
          <AppErrorBoundary key={section}>{projectId ? <ProjectOutlet /> : <Outlet />}</AppErrorBoundary>
        </div>
      </main>
    </div>
  );

  return (
    <PageTitleProvider>
      <SettingsDialogProvider>
        {/* Printing shows only the page: no top bar or project bar, and the whole page, not its scrolled view. */}
        <div className="flex h-dvh flex-col overflow-hidden bg-canvas text-ink print:block print:h-auto print:overflow-visible">
          <a
            href="#main-content"
            onClick={(event) => {
              event.preventDefault();
              mainRef.current?.focus();
            }}
            className="sr-only rounded-md bg-surface text-callout font-medium text-ink shadow-popover focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:px-3 focus:py-2"
          >
            {t('shell.skip')}
          </a>
          {projectId ? (
            <ProjectProvider key={projectId} projectId={projectId}>
              {content}
            </ProjectProvider>
          ) : (
            content
          )}
        </div>
      </SettingsDialogProvider>
    </PageTitleProvider>
  );
}
