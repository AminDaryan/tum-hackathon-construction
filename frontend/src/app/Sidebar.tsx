import { Menu } from 'lucide-react';
import { useState } from 'react';
import { Dialog as AriaDialog, Modal, ModalOverlay } from 'react-aria-components';
import { useLocation, useMatch } from 'react-router-dom';
import { IconButton } from '../components/IconButton.tsx';
import { useI18n } from '../i18n/useI18n.ts';
import { useSession } from '../stores/useSession.ts';
import { Brand } from './Brand.tsx';
import { USERS_ITEM } from './navigation.ts';
import { SidebarProjects } from './SidebarProjects.tsx';
import { SidebarUsers } from './SidebarUsers.tsx';
import { useSidebarLists } from './useSidebarLists.ts';

/** The menu button's place, the same in the top bar and in the open navigation: its icon on the page margin. */
export const MENU_BUTTON_CLASS = '-ml-2 pointer-coarse:-ml-4';

/**
 * The navigation, opened over the page by the menu button at the leading edge of the top bar:
 * Projects (a few projects) and, for those who manage accounts, Users (a few accounts), each
 * with a + that creates one. It slides in from the left over a dimmed page, with the same button
 * and the mark at the same place, and closes with that button, Escape, a click beside it, or by
 * going anywhere. The lists are read once the app is open, so they are there when it opens. A
 * project's own pages are in the bar under the top bar (ProjectNav); Settings is in the user menu.
 */
export function Sidebar() {
  const { t } = useI18n();
  const { me, meError, can } = useSession();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [shownAt, setShownAt] = useState(location.key);
  // Going anywhere closes it (a link in it, its +, or the browser's Back).
  if (shownAt !== location.key) {
    setShownAt(location.key);
    if (open) setOpen(false);
  }
  const projectMatch = useMatch('/projects/:projectId/*');
  const projectId = projectMatch && projectMatch.params.projectId !== 'new' ? (projectMatch.params.projectId ?? null) : null;
  const userMatch = useMatch('/users/:userId');
  const userId = userMatch?.params.userId ?? null;
  // `can` allows everything until the session says who is signed in, so the accounts are read
  // only once it has answered.
  const withUsers = !USERS_ITEM.permission || can(USERS_ITEM.permission);
  const lists = useSidebarLists({ readUsers: withUsers && (Boolean(me) || Boolean(meError)) });
  return (
    <>
      <IconButton icon={Menu} label={t('nav.open')} aria-haspopup="dialog" aria-expanded={open} onPress={() => setOpen(true)} className={MENU_BUTTON_CLASS} />
      <ModalOverlay
        isOpen={open}
        onOpenChange={setOpen}
        isDismissable
        className="fixed inset-0 z-50 bg-scrim data-entering:animate-[scrim-in_200ms_var(--ease-standard)] data-exiting:animate-[scrim-out_160ms_var(--ease-standard)_forwards]"
      >
        <Modal className="fixed inset-y-0 left-0 flex w-sidebar max-w-[calc(100vw-3.5rem)] flex-col border-r border-hairline bg-sidebar shadow-overlay outline-none data-entering:animate-[drawer-in_200ms_var(--ease-standard)] data-exiting:animate-[drawer-out_160ms_var(--ease-standard)_forwards]">
          <AriaDialog aria-label={t('nav.label')} className="flex min-h-0 flex-1 flex-col outline-none">
            <div className="flex h-14 shrink-0 items-center gap-2 border-b border-hairline px-6 max-sm:px-4">
              <IconButton icon={Menu} label={t('nav.close')} onPress={() => setOpen(false)} className={MENU_BUTTON_CLASS} />
              <Brand />
            </div>
            <nav aria-label={t('nav.label')} className="flex min-h-0 flex-1 flex-col">
              <ul className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overflow-x-hidden p-2">
                <SidebarProjects list={lists.projects} projectId={projectId} />
                {withUsers && <SidebarUsers list={lists.users} userId={userId} />}
              </ul>
            </nav>
          </AriaDialog>
        </Modal>
      </ModalOverlay>
    </>
  );
}
