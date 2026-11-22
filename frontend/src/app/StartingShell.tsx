import { ArrowLeft, Menu } from 'lucide-react';
import { matchPath, useLocation } from 'react-router-dom';
import { HIT_SQUARE } from '../components/hitTarget.ts';
import { cx } from '../utils/classNames.ts';
import { Skeleton } from '../components/Skeleton.tsx';
import { useI18n } from '../i18n/useI18n.ts';
import { sectionOf } from './navigation.ts';
import { Brand } from './Brand.tsx';
import { ProjectNav } from './ProjectNav.tsx';
import { MENU_BUTTON_CLASS } from './Sidebar.tsx';
import { TitlePlaceholder, TOP_BAR_CLASS, TOP_BAR_RULE } from './TopBar.tsx';

interface StartingShellProps {
  label: string;
}

/**
 * What shows while the application waits for the server's health check: the application's own
 * frame (the top bar with the menu button, the mark and the section's title, and on a project's
 * page the bar with the project's pages) over an empty page area, so nothing moves when the page
 * arrives. What the
 * page needs loads after this and shows its own placeholder in the same place. A page that names
 * itself (a project, a file) has its title and back button as grey shapes; the avatar is a grey
 * circle as in the user menu. It is only a picture: inert and hidden from
 * screen readers, which hear the status (`label`).
 */
export function StartingShell({ label }: StartingShellProps) {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const projectMatch = matchPath('/projects/:projectId/*', pathname);
  const projectId = projectMatch && projectMatch.params.projectId !== 'new' ? projectMatch.params.projectId : null;
  const namedByPage = Boolean(projectId) || pathname.startsWith('/projects/new') || pathname.startsWith('/documents/');
  const section = sectionOf(pathname);
  const Icon = section?.icon;
  const sectionTitle = section ? t(section.labelKey) : null;
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-canvas text-ink">
      <p role="status" className="sr-only">
        {label}
      </p>
      {/* A picture of the frame: inert and hidden from screen readers, the status says what happens. */}
      <div inert aria-hidden="true" className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className={TOP_BAR_CLASS}>
          <div className="flex shrink-0 items-center gap-2">
            <span className={cx('inline-flex shrink-0 items-center justify-center text-ink-tertiary', HIT_SQUARE, MENU_BUTTON_CLASS)}>
              <Menu className="size-4" strokeWidth={1.75} />
            </span>
            <Brand />
          </div>
          <span className={TOP_BAR_RULE} />
          <div className="flex min-w-0 flex-1 items-center gap-3">
            {namedByPage ? (
              <span aria-hidden="true" className={cx('-ml-2 inline-flex shrink-0 items-center justify-center text-ink-tertiary', HIT_SQUARE)}>
                <ArrowLeft className="size-4" strokeWidth={1.75} />
              </span>
            ) : (
              Icon && (
                <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-accent-subtle text-accent-strong">
                  <Icon aria-hidden="true" className="size-4" strokeWidth={1.75} />
                </span>
              )
            )}
            {namedByPage || !sectionTitle ? (
              <TitlePlaceholder subtitle={namedByPage} />
            ) : (
              <div className="min-w-0">
                {/* Not a heading: the page that follows brings the page's h1. */}
                <p className="truncate text-headline leading-tight text-ink">{sectionTitle}</p>
                {section?.hintKey && (
                  <p className="truncate text-caption leading-tight text-ink-tertiary max-sm:hidden">{t(section.hintKey)}</p>
                )}
              </div>
            )}
          </div>
          <div aria-hidden="true" className="flex shrink-0 p-1">
            <Skeleton className="size-8 shrink-0 rounded-full" />
          </div>
        </div>
        {projectId && <ProjectNav projectId={projectId} />}
        <div className="min-h-0 flex-1" />
      </div>
    </div>
  );
}
