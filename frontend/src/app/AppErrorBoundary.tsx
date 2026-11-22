import { Component, type ReactNode } from 'react';
import { ErrorState } from '../components/ErrorState.tsx';
import { t } from '../i18n/messages.ts';

/**
 * Catches rendering errors in a page so one broken view does not blank the whole app.
 * The shell remounts it on navigation (keyed by section), which clears the error.
 */
interface AppErrorBoundaryProps {
  children?: ReactNode;
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, { error: unknown }> {
  state = { error: null };

  static getDerivedStateFromError(error: unknown) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorState
          error={this.state.error}
          title={t('This view failed to render')}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
