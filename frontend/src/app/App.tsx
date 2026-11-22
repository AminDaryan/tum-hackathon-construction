import { useState } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { AppProviders } from './AppProviders.tsx';
import { AppRoutes } from './AppRoutes.tsx';
import { PhoneLanding } from './PhoneLanding.tsx';

/**
 * Root component: browser router, providers and routes. Navigations render at once rather than
 * in a transition: in a transition the address already names the new page while the old page,
 * its highlighted navigation item and its tab title stay on screen until the new one is ready.
 */
export function App() {
  const [continueOnPhone, setContinueOnPhone] = useState(false);
  return (
    <BrowserRouter useTransitions={false}>
      <AppProviders>
        <div className={continueOnPhone ? 'phone-app-continued' : undefined}>
          <AppRoutes />
        </div>
        <PhoneLanding onContinue={() => setContinueOnPhone(true)} />
      </AppProviders>
    </BrowserRouter>
  );
}
