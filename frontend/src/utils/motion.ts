import { prefersReducedMotion } from '../app/accessibility.ts';

/** How long new content takes to fade in, and closing content to fade out (the motion tokens). */
const FADE_IN_MS = 150;
const FADE_OUT_MS = 120;

function canAnimate(element: HTMLElement | null): element is HTMLElement {
  return element !== null && typeof element.animate === 'function' && !prefersReducedMotion();
}

function standardEasing() {
  return getComputedStyle(document.documentElement).getPropertyValue('--ease-standard').trim() || 'ease-out';
}

/**
 * Fades in content that has just replaced other content in the same place (another page, another
 * tab), so the change reads as one; nothing with reduced motion, or where the browser cannot
 * animate an element.
 */
export function fadeIn(element: HTMLElement | null) {
  if (!canAnimate(element)) return;
  element.animate([{ opacity: 0 }, { opacity: 1 }], { duration: FADE_IN_MS, easing: standardEasing() });
}

/**
 * Fades out something that closes (a menu React draws itself), then calls `done`, which removes
 * it; `done` at once with reduced motion, or where the browser cannot animate an element.
 */
export function fadeOut(element: HTMLElement | null, done: () => void) {
  if (!canAnimate(element)) {
    done();
    return;
  }
  element.animate([{ opacity: 1 }, { opacity: 0 }], { duration: FADE_OUT_MS, easing: standardEasing(), fill: 'forwards' }).finished.then(done, done);
}
