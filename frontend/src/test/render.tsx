/**
 * Renders the real application (routes, shell, providers) at a URL inside a MemoryRouter, with
 * StrictMode as in main.tsx. A hidden probe exposes the current location for assertions.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { AppProviders } from '../app/AppProviders.tsx';
import { AppRoutes } from '../app/AppRoutes.tsx';
import { ACTIVE_DOCUMENT_STORAGE_KEY } from '../stores/activeDocumentStorage.ts';

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location" hidden>
      {`${location.pathname}${location.search}`}
    </output>
  );
}

/**
 * @param options `activeDocumentId`
 *   pre-selects the active document; `userOptions` configures user-event
 */
export function renderApp(
  path: string = '/',
  {
    activeDocumentId,
    userOptions,
  }: {
    activeDocumentId?: string;
    userOptions?: Parameters<typeof userEvent.setup>[0];
  } = {},
) {
  if (activeDocumentId) {
    window.localStorage.setItem(ACTIVE_DOCUMENT_STORAGE_KEY, activeDocumentId);
  }
  const user = userEvent.setup(userOptions);
  const result = render(
    <StrictMode>
      <MemoryRouter initialEntries={[path]}>
        <AppProviders>
          <AppRoutes />
          <LocationProbe />
        </AppProviders>
      </MemoryRouter>
    </StrictMode>,
  );
  return {
    ...result,
    user,
    location: () => screen.getByTestId('location').textContent,
  };
}
