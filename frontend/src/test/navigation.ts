import { screen, within } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';

/** Opens the navigation with the menu button of the top bar, and returns queries within it. */
export async function openNavigation(user: UserEvent) {
  await user.click(screen.getByRole('button', { name: 'Open the navigation' }));
  return within(await screen.findByRole('navigation', { name: 'Primary' }));
}

/** Queries within the project's bar under the top bar (its pages), once the application shows it. */
export async function findProjectNav() {
  return within(await screen.findByRole('navigation', { name: 'Project' }));
}
