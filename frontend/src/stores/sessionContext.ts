import { createContext } from 'react';
import type { Health, Me } from '../services/apiTypes.ts';

export type Permission = 'read' | 'write' | 'manage_users';

export interface SessionContextValue {
  /** GET /health, once loaded */
  health: Health | null;
  /** whether the server asks for an access token */
  authRequired: boolean;
  /** whether this tab holds an access token */
  signedIn: boolean;
  /** remembers a token the server accepted */
  signIn: (token: string) => void;
  /** forgets the token; the sign-in dialog appears again */
  signOut: () => void;
  /** who the application acts for (GET /me), once loaded */
  me: Me | null;
  /** why GET /me failed */
  meError: Error | null;
  /** loads GET /me again (after changing one's own account) */
  reloadMe: () => void;
  /**
   * whether the role allows it; true while GET /me has not answered, so the server stays the one
   * that refuses
   */
  can: (permission: Permission) => boolean;
}

export const SessionContext = createContext<SessionContextValue | null>(null);
