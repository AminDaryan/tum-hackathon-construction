import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import { SignInDialog } from './SignInDialog.tsx';

describe('SignInDialog', () => {
  it('focuses the token field in the commit that shows the dialog', async () => {
    // Rendered the way the browser renders it, outside act(): act() would flush every effect
    // before the test looks. A focus set in an effect that runs after the commit (useEffect)
    // leaves the dialog on screen for a moment with nothing focused; the MutationObserver,
    // which runs right after the commit that adds the dialog, sees that moment.
    const reactGlobals = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
    const previous = reactGlobals.IS_REACT_ACT_ENVIRONMENT;
    reactGlobals.IS_REACT_ACT_ENVIRONMENT = false;
    const container = document.body.appendChild(document.createElement('div'));
    const focusedWhenShown: boolean[] = [];
    const observer = new MutationObserver(() => {
      const field = container.querySelector('input[name="access-token"]');
      if (field && focusedWhenShown.length === 0) focusedWhenShown.push(document.activeElement === field);
    });
    observer.observe(container, { childList: true, subtree: true });
    const root = createRoot(container);
    try {
      root.render(<SignInDialog onSignedIn={() => {}} />);
      await new Promise((resolve) => {
        setTimeout(resolve, 20);
      });
      expect(focusedWhenShown).toEqual([true]);
    } finally {
      observer.disconnect();
      root.unmount();
      container.remove();
      reactGlobals.IS_REACT_ACT_ENVIRONMENT = previous;
    }
  });
});
