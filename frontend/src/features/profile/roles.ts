/**
 * How each role looks: its badge tone, icon and avatar colours. The texts are in the i18n
 * messages (`role.<id>`, `role.<id>.description`).
 */
import { ClipboardCheck, Eye, ShieldCheck, type LucideIcon } from 'lucide-react';
import type { BadgeTone } from '../../components/Badge.tsx';
import type { UserAccount } from '../../services/apiTypes.ts';

interface RoleStyle {
  tone: BadgeTone;
  icon: LucideIcon;
  /** the gradient classes of the avatar */
  avatar: string;
}

export const ROLES = Object.freeze<UserAccount['role'][]>(['admin', 'reviewer', 'viewer']);

export const ROLE_STYLE: Readonly<Record<string, RoleStyle>> = Object.freeze({
  admin: { tone: 'accent', icon: ShieldCheck, avatar: 'from-accent to-[#2f8f86]' },
  reviewer: { tone: 'context', icon: ClipboardCheck, avatar: 'from-context to-[#4b7fc4]' },
  viewer: { tone: 'neutral', icon: Eye, avatar: 'from-[#6b6862] to-[#8c8982]' },
});

export const PERMISSIONS = Object.freeze(['read', 'write', 'manage_users']);

/** Up to two initials: "Anna Schmidt" is AS, "anna" is AN, an empty name is a question mark. */
export function initials(name: string | null | undefined): string {
  const words = String(name ?? '').trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
}
