/**
 * The projects and users the sidebar lists under its two sections, and the signal that has it
 * read them again after one is created, renamed or deleted.
 */

/** How many projects, or users, the sidebar lists under its section. */
export const SIDEBAR_LIST_SIZE = 5;

/**
 * The items the sidebar lists: the first `limit` in the order given, then the open one when it
 * is not among them, so its row is always there. `more` says whether some are left out.
 */
export function sidebarItems<T>(
  items: readonly T[],
  openId: string | null,
  idOf: (item: T) => string,
  limit = SIDEBAR_LIST_SIZE,
): { shown: T[]; more: boolean } {
  const first = items.slice(0, limit);
  const open = openId !== null && !first.some((item) => idOf(item) === openId) ? items.find((item) => idOf(item) === openId) : undefined;
  const shown = open ? [...first, open] : first;
  return { shown, more: items.length > shown.length };
}

const listeners = new Set<() => void>();

/** Has the sidebar read its projects and users again: call it after one is created, renamed or deleted. */
export function refreshSidebarLists(): void {
  for (const listener of listeners) listener();
}

/** Calls `listener` on each refreshSidebarLists(); returns the function that stops it. */
export function onSidebarListsRefresh(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
