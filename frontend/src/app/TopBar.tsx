import { ArrowLeft, Eye } from 'lucide-react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Badge } from '../components/Badge.tsx';
import { HIT_TARGET } from '../components/hitTarget.ts';
import { IconButton } from '../components/IconButton.tsx';
import { Skeleton } from '../components/Skeleton.tsx';
import { NotificationsButton } from '../features/collaboration/NotificationsButton.tsx';
import { ProfileMenu } from '../features/profile/ProfileMenu.tsx';
import { useI18n } from '../i18n/useI18n.ts';
import { useSession } from '../stores/useSession.ts';
import { cx } from '../utils/classNames.ts';
import { Brand } from './Brand.tsx';
import { sectionOf } from './navigation.ts';
import { usePageTitleValue } from './pageTitle.tsx';
import { Sidebar } from './Sidebar.tsx';

/** The bar's frame, shared with the placeholder shown while the application starts. */
export const TOP_BAR_CLASS =
  'z-30 flex h-14 shrink-0 items-center gap-4 border-b border-hairline bg-surface/90 px-6 backdrop-blur supports-[backdrop-filter]:bg-surface/75 max-sm:px-4';

/** The hairline between the mark and the page's title, shared in the same way. */
export const TOP_BAR_RULE = 'h-6 w-px shrink-0 bg-hairline';

/** The page a page belongs to, before its title: quieter than the title, and a link to it. */
const PARENT_LINK =
  'inline-flex min-w-0 max-w-64 items-center rounded-sm text-headline font-normal text-ink-secondary underline-offset-4 outline-none transition-colors hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus';

/**
 * A title and a subtitle that are still loading, as grey shapes of their size. A missing title
 * keeps the page's h1 for screen readers, named `label` (the section); without `label` there is
 * no h1 (the frame shown while the application starts: the page brings its own).
 */
interface TitlePlaceholderProps {
  title?: string | null;
  label?: string;
  subtitle?: boolean;
}

export function TitlePlaceholder({ title = null, label, subtitle = true }: TitlePlaceholderProps) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      {title ? (
        <h1 className="truncate text-headline leading-tight text-ink">{title}</h1>
      ) : (
        <>
          {label && <h1 className="sr-only">{label}</h1>}
          <Skeleton className="h-3.5 w-48 max-w-full" />
        </>
      )}
      {subtitle && <Skeleton className="h-2.5 w-72 max-w-full max-sm:hidden" />}
    </div>
  );
}

/**
 * The bar across the top of the window, and the page's only title (its h1): at the leading edge
 * the menu button that opens the navigation over the page, the mark and "Desvio"; after a
 * hairline, the title, led by the page it belongs to like a breadcrumb ("Project / file.D86",
 * the project a link to it), or by a back button, or else by the section's icon. A page names
 * itself with `usePageTitle`; otherwise the bar names the section. At the trailing edge: the
 * reviewer's notifications, a "Read only" mark for viewers and the avatar that opens the user
 * menu.
 */
export function TopBar() {
  const { t } = useI18n();
  const { can, me } = useSession();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const page = usePageTitleValue();
  const section = sectionOf(pathname);
  const Icon = section?.icon;
  const readOnly = Boolean(me) && !can('write');
  // An address of no section (an old one on its way to its new place) has no title of its own
  // until its page sets one: the not-found page names itself.
  const sectionTitle = section ? t(section.labelKey) : null;
  const title = page?.title ?? sectionTitle;
  const subtitle = page ? page.subtitle : section?.hintKey ? t(section.hintKey) : null;
  const parent = page?.parent ?? null;
  const back = page?.back ?? null;
  return (
    <header aria-label={t('shell.topBar')} className={TOP_BAR_CLASS}>
      <div className="flex shrink-0 items-center gap-2">
        <Sidebar />
        <Brand />
      </div>
      <span aria-hidden="true" className={TOP_BAR_RULE} />
      <div className={cx('flex min-w-0 flex-1 items-center', parent ? 'gap-2' : 'gap-3')}>
        {parent ? (
          <>
            {parent.label ? (
              <Link to={parent.to} title={parent.label} className={cx(PARENT_LINK, HIT_TARGET)}>
                <span className="truncate">{parent.label}</span>
              </Link>
            ) : (
              <Skeleton className="h-3.5 w-24 shrink-0" />
            )}
            <span aria-hidden="true" className="shrink-0 text-headline font-normal text-ink-tertiary">
              /
            </span>
          </>
        ) : back ? (
          <IconButton icon={ArrowLeft} label={back.label} onPress={() => navigate(back.to)} className="-ml-2" />
        ) : (
          Icon && (
            <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-accent-subtle text-accent-strong">
              <Icon aria-hidden="true" className="size-4" strokeWidth={1.75} />
            </span>
          )
        )}
        {page?.pending && (!page.title || !subtitle) ? (
          <TitlePlaceholder title={page.title} label={sectionTitle ?? undefined} subtitle={!subtitle} />
        ) : !title ? (
          <TitlePlaceholder subtitle={false} />
        ) : (
          <div className="min-w-0">
            <h1 className="truncate text-headline leading-tight text-ink" title={title}>
              {title}
            </h1>
            {subtitle && (
              <p className="truncate text-caption leading-tight text-ink-tertiary max-sm:hidden" title={subtitle}>
                {subtitle}
              </p>
            )}
          </div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <NotificationsButton />
        {readOnly && (
          <Badge tone="neutral" icon={Eye} title={t('profile.readOnlyHint')}>
            {t('profile.readOnly')}
          </Badge>
        )}
        <ProfileMenu />
      </div>
    </header>
  );
}
