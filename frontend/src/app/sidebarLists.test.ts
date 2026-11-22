import { describe, expect, it, vi } from 'vitest';
import { onSidebarListsRefresh, refreshSidebarLists, sidebarItems } from './sidebarLists.ts';

const ids = ['a', 'b', 'c', 'd'];
const same = (id: string) => id;

describe('sidebarItems', () => {
  it('lists the first ones and says whether more are left out', () => {
    expect(sidebarItems(ids, null, same, 2)).toEqual({ shown: ['a', 'b'], more: true });
    expect(sidebarItems(ids, null, same, 4)).toEqual({ shown: ids, more: false });
    expect(sidebarItems([], null, same, 2)).toEqual({ shown: [], more: false });
  });

  it('adds the open one after them when it is not among them', () => {
    expect(sidebarItems(ids, 'd', same, 2)).toEqual({ shown: ['a', 'b', 'd'], more: true });
    expect(sidebarItems(ids, 'c', same, 3)).toEqual({ shown: ['a', 'b', 'c'], more: true });
    expect(sidebarItems(ids, 'd', same, 3)).toEqual({ shown: ['a', 'b', 'c', 'd'], more: false });
    // An open id the list does not have adds nothing.
    expect(sidebarItems(ids, 'x', same, 2)).toEqual({ shown: ['a', 'b'], more: true });
  });
});

describe('refreshSidebarLists', () => {
  it('calls every listener until it stops', () => {
    const listener = vi.fn();
    const stop = onSidebarListsRefresh(listener);
    refreshSidebarLists();
    expect(listener).toHaveBeenCalledTimes(1);
    stop();
    refreshSidebarLists();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
