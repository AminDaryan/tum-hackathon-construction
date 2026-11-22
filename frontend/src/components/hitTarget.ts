/**
 * Hit areas: every interactive control is at least 32 × 32 CSS px with a mouse, which meets WCAG
 * 2.2 target size (minimum, 24 × 24), and at least 48 × 48 when the primary pointer is coarse
 * (a finger; Tailwind's `pointer-coarse:` variant), after Material Design (48 × 48 dp). The
 * compact mouse size keeps the dense workspace readable; touch keeps the large size. The shared
 * components apply these classes, so a feature that builds on them gets the sizes as well.
 *
 * The browser test e2e/touch-targets.spec.ts measures them in the built interface.
 */

/** At least 32 × 32 px (48 × 48 on coarse pointers); content may make the control larger. */
export const HIT_TARGET = 'min-h-8 min-w-8 pointer-coarse:min-h-12 pointer-coarse:min-w-12';

/** Exactly 32 × 32 px (48 × 48 on coarse pointers), for icon-only controls. */
export const HIT_SQUARE = 'size-8 pointer-coarse:size-12';

/** 32 px tall (48 on coarse pointers), for text fields and selects that fill their container. */
export const HIT_HEIGHT = 'h-8 pointer-coarse:h-12';

/** At least 32 px tall (48 on coarse pointers), for controls whose text makes them wide enough. */
export const HIT_MIN_HEIGHT = 'min-h-8 pointer-coarse:min-h-12';
