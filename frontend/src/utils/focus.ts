/**
 * Moves focus to the heading that labels the section around `element` (a `section` with
 * `aria-labelledby`, as rendered by Section and InspectorSection). Call it before the focused
 * control is replaced, for example by a new page of results or the actions left after a review
 * decision, so that keyboard focus does not drop to the page body.
 */
export function focusSectionHeading(element: Element | null | undefined): void {
  const section = element?.closest('section[aria-labelledby]');
  const heading = section && document.getElementById(section.getAttribute('aria-labelledby') ?? '');
  if (heading) {
    heading.tabIndex = -1;
    heading.focus();
  }
}
