import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LongitudinalSignal } from '../types';
import { LongitudinalSignalConflictError, getLongitudinalSignal, reviewLongitudinalSignal } from '../services/api';
import { IntelligenceReviewPanel } from './IntelligenceReviewPanel';

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api');
  return { ...actual, getLongitudinalSignal: vi.fn(), reviewLongitudinalSignal: vi.fn() };
});

const mockedGetSignal = vi.mocked(getLongitudinalSignal);
const mockedReview = vi.mocked(reviewLongitudinalSignal);

const draft: LongitudinalSignal = {
  id: '00000000-0000-0000-0000-000000000101', client_id: '00000000-0000-0000-0000-000000000201',
  canonical_key: 'sleep-consistency', signal_kind: 'theme', temporal_state: 'active', trend_direction: 'stable',
  summary: 'Sleep consistency is an active theme.', explanation: 'Approved evidence supports this theme.',
  trust_state: 'draft', first_observed_at: '2026-01-01T00:00:00Z', last_observed_at: '2026-01-02T00:00:00Z',
  observation_count: 1, version: 1, reviewed_at: null,
  evidence: [{ analysis_id: '00000000-0000-0000-0000-000000000301', artifact_kind: 'finding', artifact_id: 'finding-1', evidence_role: 'supports' }],
};

afterEach(() => vi.clearAllMocks());

describe('IntelligenceReviewPanel', () => {
  it('requires explicit approval for a draft signal', async () => {
    const user = userEvent.setup(); mockedReview.mockResolvedValue({ ...draft, trust_state: 'trusted', version: 2 });
    render(<IntelligenceReviewPanel signal={draft} />);
    expect(screen.getByText(/draft — human review required/i)).toBeInTheDocument();
    expect(mockedReview).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Approve signal' }));
    expect(mockedReview).toHaveBeenCalledWith(draft.id, { action: 'approve', expected_version: 1, reason: null });
  });

  it('visually separates needs-revalidation and offers revalidate', async () => {
    render(<IntelligenceReviewPanel signal={{ ...draft, trust_state: 'needs_revalidation' }} />);
    expect(screen.getByText('needs revalidation', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Revalidate signal' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve signal' })).not.toBeInTheDocument();
  });

  it('makes evidence locators inspectable without rendering raw transcript text', () => {
    render(<IntelligenceReviewPanel signal={draft} />);
    expect(screen.getByText('Analysis finding: finding-1')).toBeInTheDocument();
    expect(screen.getByText('supports')).toBeInTheDocument();
    expect(screen.queryByText(/raw conversation/i)).not.toBeInTheDocument();
  });

  it('preserves unsaved edit text on a same-version rerender', async () => {
    const user = userEvent.setup(); const view = render(<IntelligenceReviewPanel signal={draft} />);
    await user.click(screen.getByRole('button', { name: 'Edit and approve signal' }));
    await user.type(screen.getByLabelText('Edited summary'), ' Reworded');
    view.rerender(<IntelligenceReviewPanel signal={{ ...draft, summary: 'Server changed presentation only' }} />);
    expect(screen.getByLabelText('Edited summary')).toHaveValue('Sleep consistency is an active theme. Reworded');
  });

  it('requires an explicit reload after conflict without automatic retry', async () => {
    const user = userEvent.setup(); mockedReview.mockRejectedValue(new LongitudinalSignalConflictError());
    mockedGetSignal.mockResolvedValue({ ...draft, version: 2, summary: 'Authoritative update' });
    render(<IntelligenceReviewPanel signal={draft} />);
    await user.click(screen.getByRole('button', { name: 'Approve signal' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/reload/i);
    expect(mockedGetSignal).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Reload signal' }));
    expect(mockedGetSignal).toHaveBeenCalledWith(draft.id);
    expect(mockedReview).toHaveBeenCalledTimes(1);
  });
});
