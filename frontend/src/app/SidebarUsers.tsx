import { UserRound } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../i18n/useI18n.ts';
import { USERS_ITEM } from './navigation.ts';
import { SidebarGroup } from './SidebarGroup.tsx';
import { SidebarLink } from './SidebarLink.tsx';
import { sidebarItems } from './sidebarLists.ts';
import type { UserAccount } from '../services/apiTypes.ts';
import type { SidebarList } from './useSidebarLists.ts';

interface SidebarUsersProps {
  list: SidebarList<UserAccount>;
  /** the user whose page is open */
  userId: string | null;
}

/**
 * Users in the navigation: the heading with a + that adds a user, the first accounts by name,
 * the open one among them, and "More users" when some are left out.
 */
export function SidebarUsers({ list, userId }: SidebarUsersProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { shown, more } = sidebarItems(list.data ?? [], userId, (user) => user.user_id);
  return (
    <SidebarGroup
      to={USERS_ITEM.to}
      end={shown.some((user) => user.user_id === userId)}
      label={t(USERS_ITEM.labelKey)}
      icon={USERS_ITEM.icon}
      addLabel={t('users.add')}
      onAdd={() => navigate('/users?add=1')}
      more={more}
      moreLabel={t('More users')}
      loading={list.data === undefined && list.loading}
    >
      {shown.map((user) => (
        <li key={user.user_id}>
          <SidebarLink to={`/users/${encodeURIComponent(user.user_id)}`} label={user.name} icon={UserRound} depth={1} />
        </li>
      ))}
    </SidebarGroup>
  );
}
