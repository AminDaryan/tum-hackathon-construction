import { useCallback, useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { prefersReducedMotion } from '../app/accessibility.ts';

/**
 * Makes everything outside `element` inert: the siblings of the element and of each of its
 * ancestors, up to the app's root. Popovers, tooltips and the screen-reader announcer live in
 * <body> beside the root, so they keep working. Returns the function that undoes it.
 */
function inertOutside(element: HTMLElement): () => void {
  const changed: Element[] = [];
  for (let node: Element = element; node.parentElement && node.parentElement !== document.body; node = node.parentElement) {
    for (const sibling of node.parentElement.children) {
      if (sibling !== node && !sibling.hasAttribute('inert')) {
        sibling.setAttribute('inert', '');
        changed.push(sibling);
      }
    }
  }
  return () => changed.forEach((sibling) => sibling.removeAttribute('inert'));
}

/**
 * Applies a change of full screen in a view transition, so the part named `full-screen` in CSS
 * grows from its place to the window and back (index.css). Without view transitions, or with
 * reduced motion, the change is applied at once.
 */
function morph(change: () => void) {
  if (typeof document.startViewTransition !== 'function' || prefersReducedMotion()) {
    change();
    return;
  }
  const transition = document.startViewTransition(() => flushSync(change));
  // Skipped (the window changed size meanwhile): the change is applied all the same.
  transition.ready.catch(() => {});
}

/**
 * Full screen for one part of a page (the sheet with its PDF view): `active` tells the part to
 * cover the window, the rest of the app turns inert meanwhile, and the browser goes full screen
 * too where it can (`requestFullscreen` on the document, so popovers still show). Leaving the
 * browser's full screen (Escape) leaves this one as well. Where the browser cannot (an iPhone),
 * the part still covers the window and its own button closes it. The part grows to the window
 * and shrinks back in a view transition, once the browser's window has its new size.
 *
 * `targetRef` holds the element that covers the window; the state outlives that element, so a
 * part that remounts (another table) stays full screen.
 */
export function useFullScreen(
  targetRef: { current: HTMLElement | null },
): { active: boolean; enter: () => void; exit: () => void } {
  const [active, setActive] = useState(false);
  // Whether the browser's full screen was asked for by this hook, so only that one is left.
  const requested = useRef(false);

  const leaveBrowserFullScreen = useCallback(() => {
    if (requested.current && document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
    requested.current = false;
  }, []);

  // The window first takes its full-screen size, then the part grows into it: a view transition
  // is skipped when the window changes size while it runs.
  const enter = useCallback(() => {
    const cover = () => morph(() => setActive(true));
    const root = document.documentElement;
    if (document.fullscreenEnabled && !document.fullscreenElement && root.requestFullscreen) {
      requested.current = true;
      root.requestFullscreen().then(cover, () => {
        requested.current = false;
        cover();
      });
    } else {
      cover();
    }
  }, []);

  // The other way round: the window first, while the part still covers it, then the part.
  const exit = useCallback(() => {
    const uncover = () => morph(() => setActive(false));
    if (requested.current && document.fullscreenElement && document.exitFullscreen) {
      requested.current = false;
      document.exitFullscreen().then(uncover, uncover);
    } else {
      requested.current = false;
      uncover();
    }
  }, []);

  // Escape (or the browser's own control) left the browser's full screen: leave ours too.
  useEffect(() => {
    if (!active) return undefined;
    const changed = () => {
      if (requested.current && !document.fullscreenElement) {
        requested.current = false;
        morph(() => setActive(false));
      }
    };
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, [active]);

  useEffect(() => {
    if (!active || !targetRef.current) return undefined;
    return inertOutside(targetRef.current);
  }, [active, targetRef]);

  useEffect(() => leaveBrowserFullScreen, [leaveBrowserFullScreen]);

  return { active, enter, exit };
}
