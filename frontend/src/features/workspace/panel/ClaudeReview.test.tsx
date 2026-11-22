import { screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_HEALTH, DEFAULT_ME, mockFetch } from '../../../test/fetchMock.ts';
import { runDetail, runSummaries } from '../../../test/fixtures.ts';
import { renderApp } from '../../../test/render.tsx';
import { projectWorkspaceRoutes, RUNS, WORKSPACE_URL } from '../../../test/workspaceRoutes.ts';

vi.mock('../../../ifc-demo/ModelViewer.tsx', () => {
  function ModelViewer() {
    return <div data-testid="model-viewer" />;
  }
  return { ModelViewer };
});

const SEND = 'Send the bill to Claude for review';

/** A finished run whose Claude review got no answer. */
const unanswered = {
  ...runDetail,
  detector_reports: [
    ...runDetail.detector_reports,
    {
      detector_id: 'llm.bill_review',
      detector_version: '1.0.0',
      status: 'skipped',
      config: {},
      rationale: null,
      issues_found: 0,
      issues_dropped: 0,
      duration_ms: 0,
      skipped_reasons: ['No pass answered: status 401 (authentication_error).'],
      limit_reached: null,
      error: null,
      notes: [],
      coverage: {},
    },
  ],
};

/** The side panel once the Risks tab has listed the risks of the run. */
async function risksTab() {
  const panel = await screen.findByRole('complementary', { name: 'Side panel' });
  await within(panel).findByRole('list', { name: 'Risks' });
  return panel;
}

describe('Claude review on the file page', () => {
  it('sends the bill on request from the end of the Risks tab and says why it was not reviewed', async () => {
    const api = mockFetch([
      { path: '/api/v1/health', respond: { ...DEFAULT_HEALTH, bill_review_available: true } },
      { method: 'POST', path: RUNS, respond: unanswered },
      ...projectWorkspaceRoutes({ runs: () => runSummaries }),
    ]);
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });
    const panel = await risksTab();

    // Offered without a local model: the default health has none.
    const models = within(panel).getByRole('region', { name: 'Language model' });
    expect(within(models).queryByRole('button', { name: /local model/ })).not.toBeInTheDocument();
    await user.click(within(models).getByRole('button', { name: SEND }));

    const [request] = api.callsTo('POST', RUNS);
    expect(JSON.parse(request.body)).toEqual({ bill_review: true });
    expect(await within(panel).findByRole('alert')).toHaveTextContent(
      'The bill was not reviewed. No pass answered: status 401 (authentication_error).',
    );
  });

  it('is not offered without a key on the server, nor to a viewer', async () => {
    const viewer = { ...DEFAULT_ME, role: 'viewer', permissions: ['read'] };
    for (const [health, me] of [
      [DEFAULT_HEALTH, DEFAULT_ME],
      [{ ...DEFAULT_HEALTH, bill_review_available: true }, viewer],
    ]) {
      mockFetch([
        { path: '/api/v1/health', respond: health },
        { path: '/api/v1/me', respond: me },
        ...projectWorkspaceRoutes({ runs: () => runSummaries }),
      ]);
      const { unmount } = renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });
      const panel = await risksTab();
      expect(within(panel).queryByRole('button', { name: SEND })).not.toBeInTheDocument();
      expect(within(panel).queryByRole('region', { name: 'Language model' })).not.toBeInTheDocument();
      unmount();
    }
  });
});
