import { createContext, useContext, useLayoutEffect, useState } from 'react';
import type { Dispatch, ReactNode, SetStateAction } from 'react';

interface PageTitle {
  title: string | null;
  subtitle: string | null;
  /** still loading what names the page: the top bar shows grey shapes */
  pending: boolean;
  /** the page this one belongs to, named before the title; a null name is still loading */
  parent: { label: string | null; to: string } | null;
  back: { label: string; to: string } | null;
}

const SetterContext = createContext<Dispatch<SetStateAction<PageTitle | null>> | null>(null);
const ValueContext = createContext<PageTitle | null>(null);

interface PageTitleProviderProps { children?: ReactNode }

/**
 * Holds the title of the page on screen for the top bar, which is the page's only title (its
 * h1): the page sets it with `usePageTitle`, and without one the top bar names the section.
 * The setter and the value are separate contexts, so a page that sets its title never re-renders
 * because of it.
 */
export function PageTitleProvider({ children }: PageTitleProviderProps) {
  const [page, setPage] = useState<PageTitle | null>(null);
  return (
    <SetterContext value={setPage}>
      <ValueContext value={page}>{children}</ValueContext>
    </SetterContext>
  );
}

/** The title the page on screen set, or null: `{ title, subtitle, pending, parent, back }`. */
export function usePageTitleValue() {
  return useContext(ValueContext);
}

/**
 * Sets the title of this page in the top bar while the page is shown. `parent` names the page
 * this one belongs to before the title, as a link to it, like a breadcrumb: `{ label, to }`,
 * such as a file's project; a null `label` shows as a grey shape while it loads. `back` instead
 * adds a back button at the leading edge: `{ label, to }`, where `label` is the button's name,
 * such as "Back to all projects". `pending` says the page is still loading what names it: the
 * top bar shows a missing title and subtitle as grey shapes of their size, so the bar does not
 * change height when they arrive.
 */
export function usePageTitle({
  title,
  subtitle = null,
  parent = null,
  back = null,
  pending = false,
}: {
  title?: string | null;
  subtitle?: string | null;
  parent?: { label: string | null; to: string } | null;
  back?: { label: string; to: string } | null;
  pending?: boolean;
}) {
  const setPage = useContext(SetterContext);
  const parentLabel = parent?.label ?? null;
  const parentTo = parent?.to ?? null;
  const backLabel = back?.label ?? null;
  const backTo = back?.to ?? null;
  useLayoutEffect(() => {
    if (!setPage || (!title && !pending)) return undefined;
    const entry: PageTitle = {
      title: title || null,
      subtitle: subtitle || null,
      pending,
      parent: parentTo ? { label: parentLabel, to: parentTo } : null,
      back: backLabel && backTo ? { label: backLabel, to: backTo } : null,
    };
    setPage(entry);
    return () => setPage((current) => (current === entry ? null : current));
  }, [setPage, title, subtitle, pending, parentLabel, parentTo, backLabel, backTo]);
}
