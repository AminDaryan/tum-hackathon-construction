import { useSyncExternalStore } from 'react';

/**
 * The reader's accessibility preferences, kept in this browser (Settings, Accessibility). Each is
 * written to an attribute of <html> that the stylesheet reads (index.html applies the saved
 * choices before the first paint, so nothing flashes):
 *
 * - `textSize` (`data-text-size`): 'default', 'large' (112.5 %) or 'larger' (125 %). Every size in
 *   the interface is in rem, so the whole page scales, with its layout.
 * - `contrast` (`data-contrast`): 'system' follows the operating system's "more contrast"
 *   setting; 'high' darkens secondary text, borders and the focus ring (lightens them in the dark
 *   scheme); 'standard' keeps the normal palette.
 * - `motion` (`data-motion`): 'system' follows "reduce motion"; 'reduce' stops animations,
 *   transitions, smooth scrolling and the 3D model's intro even when the system allows them.
 * - `underlineLinks` (`data-underline-links`): links in the page underlined, not only coloured.
 * - `readableText` (`data-readable-text`): more space between letters, words and lines.
 * - `strongFocus` (`data-strong-focus`): a thicker keyboard focus ring with a halo.
 */
export const STORAGE_KEY = 'twb.accessibility';

export interface AccessibilityPreferences {
  textSize: 'default' | 'large' | 'larger';
  contrast: 'system' | 'standard' | 'high';
  motion: 'system' | 'reduce';
  underlineLinks: boolean;
  readableText: boolean;
  strongFocus: boolean;
}

type AccessibilityChoice = 'textSize' | 'contrast' | 'motion';

export const DEFAULT_PREFERENCES: Readonly<AccessibilityPreferences> = Object.freeze({
  textSize: 'default',
  contrast: 'system',
  motion: 'system',
  underlineLinks: false,
  readableText: false,
  strongFocus: false,
});

export const CHOICES: Readonly<Record<AccessibilityChoice, readonly string[]>> = Object.freeze({
  textSize: ['default', 'large', 'larger'],
  contrast: ['system', 'standard', 'high'],
  motion: ['system', 'reduce'],
});

const CONTRAST_QUERY = '(prefers-contrast: more)';
const MOTION_QUERY = '(prefers-reduced-motion: reduce)';
const listeners = new Set<() => void>();

function matches(query: string) {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches;
}

/** Keeps only known keys with allowed values; anything else falls back to the default. */
export function normalize(value: unknown): Readonly<AccessibilityPreferences> {
  const source: Record<string, unknown> = value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
  const result: Record<string, unknown> = { ...DEFAULT_PREFERENCES };
  for (const [key, allowed] of Object.entries(CHOICES)) {
    if (allowed.includes(source[key] as string)) result[key] = source[key];
  }
  for (const key of ['underlineLinks', 'readableText', 'strongFocus']) {
    if (typeof source[key] === 'boolean') result[key] = source[key];
  }
  return Object.freeze(result) as Readonly<AccessibilityPreferences>;
}

function read() {
  try {
    return normalize(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? 'null'));
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

let current = typeof window === 'undefined' ? DEFAULT_PREFERENCES : read();

/** The attribute values for preferences, with 'system' resolved against the operating system. */
function resolve(preferences = current) {
  return {
    textSize: preferences.textSize,
    contrast: preferences.contrast === 'system' ? (matches(CONTRAST_QUERY) ? 'high' : 'standard') : preferences.contrast,
    motion: preferences.motion === 'system' ? (matches(MOTION_QUERY) ? 'reduce' : 'full') : preferences.motion,
    underlineLinks: preferences.underlineLinks,
    readableText: preferences.readableText,
    strongFocus: preferences.strongFocus,
  };
}

function apply() {
  const resolved = resolve();
  const data = document.documentElement.dataset;
  data.textSize = resolved.textSize;
  data.contrast = resolved.contrast;
  data.motion = resolved.motion;
  data.underlineLinks = String(resolved.underlineLinks);
  data.readableText = String(resolved.readableText);
  data.strongFocus = String(resolved.strongFocus);
  listeners.forEach((listener) => listener());
}

function save() {
  try {
    const changed = (Object.keys(current) as (keyof AccessibilityPreferences)[]).some((key) => DEFAULT_PREFERENCES[key] !== current[key]);
    if (changed) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage may be unavailable (private mode); the choice then lasts for this page.
  }
}

/** Changes one preference and applies it at once. */
export function setAccessibilityPreference(key: keyof AccessibilityPreferences, value: string | boolean) {
  current = normalize({ ...current, [key]: value });
  save();
  apply();
}

/** Back to the defaults (which follow the operating system). */
export function resetAccessibilityPreferences() {
  current = DEFAULT_PREFERENCES;
  save();
  apply();
}

/** Applies the saved preferences and follows the system settings while they are 'system'. */
export function startAccessibility() {
  current = read();
  apply();
  if (typeof window.matchMedia !== 'function') return () => {};
  const queries = [window.matchMedia(CONTRAST_QUERY), window.matchMedia(MOTION_QUERY)];
  queries.forEach((query) => query.addEventListener?.('change', apply));
  return () => queries.forEach((query) => query.removeEventListener?.('change', apply));
}

/**
 * Whether motion should be reduced: the reader's choice here, or the system setting. Code that
 * animates outside CSS (smooth scrolling, the 3D viewer) asks this.
 */
export function prefersReducedMotion() {
  if (typeof document !== 'undefined' && document.documentElement.dataset.motion === 'reduce') return true;
  if (current.motion === 'reduce') return true;
  return matches(MOTION_QUERY);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The reader's preferences, re-rendering when they change. */
export function useAccessibilityPreferences() {
  return useSyncExternalStore(subscribe, () => current, () => DEFAULT_PREFERENCES);
}
