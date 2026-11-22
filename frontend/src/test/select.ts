import { screen, within, type ByRoleOptions } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';

/**
 * The trigger button of a React Aria Select, found by its visible label. Its accessible name is
 * "<current value> <label>", so it is looked up through the label instead.
 */
export function getSelect(label: string, container: HTMLElement = document.body) {
  const trigger = within(container)
    .getAllByRole('button')
    .find((button) =>
      (button.getAttribute('aria-labelledby') ?? '')
        .split(' ')
        .some((id) => id && document.getElementById(id)?.textContent === label),
    );
  if (!trigger) throw new Error(`No select labelled "${label}"`);
  return trigger;
}

/** Opens the Select labelled `label` and chooses the option named `option` (a text match). */
export async function chooseOption(
  user: UserEvent,
  label: string,
  option: ByRoleOptions['name'],
  container?: HTMLElement,
) {
  await user.click(getSelect(label, container));
  await user.click(await screen.findByRole('option', { name: option }));
}
