import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  AnalysisReviewConflictError,
  getAnalysis,
  updateAnalysisReview,
} from '../services/api';
import type { PersistedAnalysisResponse } from '../types';
import AnalysisDetailPage from './AnalysisDetailPage';

vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>();
  return {
    ...original,
    getAnalysis: vi.fn(),
    updateAnalysisReview: vi.fn(),
  };
});

const mockedGetAnalysis = vi.mocked(getAnalysis);
const mockedUpdateAnalysisReview = vi.mocked(updateAnalysisReview);
const analysisId = '00000000-0000-4000-8000-000000000001';

const evidence = {
  message_id: 'msg-001',
  day: 'Day 1',
  speaker: 'Client',
  quote: 'I slept only five hours last night.',
};

const finding = {
  finding_id: 'finding-sleep',
  category: 'sleep',
  title: 'Sleep pattern',
  statement: 'The client reported a short sleep period.',
  classification: 'client_reported_information',
  confidence: 0.86,
  evidence: [evidence],
  review_status: 'pending' as const,
};

const analysis: PersistedAnalysisResponse = {
  analysis_id: analysisId,
  status: 'completed',
  created_at: '2026-01-01T10:30:00Z',
  client_reference: 'ANON-001',
  analysis_period: 'Week 1',
  weekly_summary: {
    ...finding,
    finding_id: 'summary-1',
    category: 'weekly_summary',
    title: 'Weekly client summary',
    statement: 'The stored weekly synthesis needs coach review.',
  },
  findings: [finding],
  risk_flags: [{
    risk_id: 'risk-fatigue',
    title: 'Fatigue attention signal',
    severity: 'high',
    rationale: 'The client reported significant fatigue.',
    classification: 'ai_generated_inference',
    confidence: 0.75,
    evidence: [evidence],
    review_status: 'pending',
  }],
  recommended_actions: [{
    action_id: 'action-follow-up',
    priority: 1,
    action: 'Contact the client for follow-up.',
    rationale: 'Fatigue warrants human review.',
    classification: 'ai_generated_inference',
    linked_finding_ids: ['finding-sleep'],
    evidence: [evidence],
    review_status: 'pending',
  }],
  missing_information: ['A complete daily sleep log is unavailable.'],
  engine: 'deterministic_evidence_baseline_v1',
  prompt_version: 'deterministic-baseline-v1',
  validation_warnings: ['Human review is required.'],
  fallback_reason: 'llm_not_configured',
  review_status: 'pending_review',
  review_note: null,
  reviewed_at: null,
  review_version: 1,
};

function renderDetail(path = `/analyses/${analysisId}`) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/analyses/:analysisId" element={<AnalysisDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('AnalysisDetailPage', () => {
  it('announces the loading state', () => {
    mockedGetAnalysis.mockReturnValue(new Promise(() => {}));
    renderDetail();

    expect(screen.getByRole('status')).toHaveTextContent('Loading saved analysis');
  });

  it('renders a successfully retrieved analysis', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByText('deterministic_evidence_baseline_v1')).toBeInTheDocument();
    expect(screen.getByText(analysisId)).toBeInTheDocument();
  });

  it('renders the current pending review state', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByText('Current status: pending review')).toBeInTheDocument();
    expect(screen.getByText('No review note saved.')).toBeInTheDocument();
    expect(screen.getByText('Not reviewed yet')).toBeInTheDocument();
  });

  it('renders approved state, note, timestamp, and version', async () => {
    mockedGetAnalysis.mockResolvedValue({
      ...analysis,
      review_status: 'approved',
      review_note: 'Reviewed carefully.',
      reviewed_at: '2026-01-02T12:00:00Z',
      review_version: 2,
    });
    renderDetail();

    expect(await screen.findByText('Current status: approved')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Reviewed carefully.')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getAllByText('Reviewed carefully.').some((item) => item.closest('dd'))).toBe(true);
  });

  it('renders changes-requested status textually', async () => {
    mockedGetAnalysis.mockResolvedValue({
      ...analysis,
      review_status: 'changes_requested',
      review_note: 'Add more evidence.',
      reviewed_at: '2026-01-02T12:00:00Z',
      review_version: 2,
    });
    renderDetail();

    expect(await screen.findByText('Current status: changes requested')).toBeInTheDocument();
  });

  it('renders the client reference', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByRole('heading', { name: 'ANON-001' })).toBeInTheDocument();
  });

  it('uses Anonymous when no client reference is stored', async () => {
    mockedGetAnalysis.mockResolvedValue({ ...analysis, client_reference: null });
    renderDetail();

    expect(await screen.findByRole('heading', { name: 'Anonymous' })).toBeInTheDocument();
  });

  it('renders the weekly summary', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByText('Weekly client summary')).toBeInTheDocument();
    expect(screen.getByText('The stored weekly synthesis needs coach review.')).toBeInTheDocument();
  });

  it('renders findings', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByText('Sleep pattern')).toBeInTheDocument();
    expect(screen.getByText('The client reported a short sleep period.')).toBeInTheDocument();
  });

  it('renders risk flags', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByText('Fatigue attention signal')).toBeInTheDocument();
    expect(screen.getByText('Severity: high')).toBeInTheDocument();
  });

  it('renders recommended actions and linked findings', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByText('Contact the client for follow-up.')).toBeInTheDocument();
    expect(screen.getByText('finding-sleep')).toBeInTheDocument();
  });

  it('renders evidence as a blockquote with source metadata', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();
    await screen.findByText('Sleep pattern');

    expect(screen.getAllByText(/I slept only five hours/)[0].closest('blockquote')).toBeInTheDocument();
    expect(screen.getAllByText('Day 1 · Client')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Message msg-001')[0]).toBeInTheDocument();
  });

  it('renders confidence as a readable percentage', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findAllByText('86% confidence')).toHaveLength(2);
    expect(screen.getByText('75% confidence')).toBeInTheDocument();
  });

  it('renders fallback status', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByText('Fallback used: llm_not_configured')).toBeInTheDocument();
  });

  it('renders validation warnings', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByText('Human review is required.')).toBeInTheDocument();
  });

  it('renders missing information', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByText('A complete daily sleep log is unavailable.')).toBeInTheDocument();
  });

  it('renders a distinct not-found state', async () => {
    mockedGetAnalysis.mockRejectedValue(new Error('The requested analysis was not found.'));
    renderDetail();

    expect(await screen.findByRole('heading', { name: 'Analysis not found' })).toBeInTheDocument();
  });

  it('renders a sanitized generic error', async () => {
    mockedGetAnalysis.mockRejectedValue(new Error('raw database detail'));
    renderDetail();

    expect(await screen.findByRole('alert')).toHaveTextContent('temporarily unavailable');
    expect(screen.queryByText('raw database detail')).not.toBeInTheDocument();
  });

  it('retries retrieval after a generic error', async () => {
    const user = userEvent.setup();
    mockedGetAnalysis
      .mockRejectedValueOnce(new Error('network detail'))
      .mockResolvedValueOnce(analysis);
    renderDetail();

    await user.click(await screen.findByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(mockedGetAnalysis).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('heading', { name: 'ANON-001' })).toBeInTheDocument();
  });

  it('links back to the analyses list', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    expect(await screen.findByRole('link', { name: /Back to analyses/i }))
      .toHaveAttribute('href', '/analyses');
  });

  it('passes the route analysis ID to getAnalysis', async () => {
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    await waitFor(() => expect(mockedGetAnalysis).toHaveBeenCalledWith(analysisId));
  });

  it('never renders an original conversation field', async () => {
    mockedGetAnalysis.mockResolvedValue({
      ...analysis,
      conversation: 'PRIVATE ORIGINAL CONVERSATION',
    } as PersistedAnalysisResponse);
    renderDetail();

    await screen.findByRole('heading', { name: 'ANON-001' });
    expect(screen.queryByText('PRIVATE ORIGINAL CONVERSATION')).not.toBeInTheDocument();
  });

  it('handles a malformed route ID without requesting data', async () => {
    renderDetail('/analyses/not-a-uuid');

    expect(await screen.findByRole('heading', { name: 'Invalid analysis link' })).toBeInTheDocument();
    expect(mockedGetAnalysis).not.toHaveBeenCalled();
  });

  it('approves without a note using the current version', async () => {
    const user = userEvent.setup();
    mockedGetAnalysis.mockResolvedValue(analysis);
    mockedUpdateAnalysisReview.mockResolvedValue({
      analysis_id: analysisId,
      review_status: 'approved',
      review_note: null,
      reviewed_at: '2026-01-02T12:00:00Z',
      review_version: 2,
    });
    renderDetail();

    await user.click(await screen.findByRole('button', { name: 'Approve analysis' }));

    expect(mockedUpdateAnalysisReview).toHaveBeenCalledWith(analysisId, {
      review_status: 'approved',
      review_note: null,
      expected_version: 1,
    });
  });

  it('sends trimmed optional approval note', async () => {
    const user = userEvent.setup();
    mockedGetAnalysis.mockResolvedValue(analysis);
    mockedUpdateAnalysisReview.mockResolvedValue({
      analysis_id: analysisId,
      review_status: 'approved',
      review_note: 'Looks good.',
      reviewed_at: '2026-01-02T12:00:00Z',
      review_version: 2,
    });
    renderDetail();

    const note = await screen.findByLabelText(/Review note/i);
    await user.type(note, '  Looks good.  ');
    await user.click(screen.getByRole('button', { name: 'Approve analysis' }));

    expect(mockedUpdateAnalysisReview).toHaveBeenCalledWith(
      analysisId,
      expect.objectContaining({ review_note: 'Looks good.' }),
    );
  });

  it('sends a valid trimmed changes-requested note', async () => {
    const user = userEvent.setup();
    mockedGetAnalysis.mockResolvedValue(analysis);
    mockedUpdateAnalysisReview.mockResolvedValue({
      analysis_id: analysisId,
      review_status: 'changes_requested',
      review_note: 'Add evidence.',
      reviewed_at: '2026-01-02T12:00:00Z',
      review_version: 2,
    });
    renderDetail();

    await user.type(await screen.findByLabelText(/Review note/i), '  Add evidence.  ');
    await user.click(screen.getByRole('button', { name: 'Request changes' }));

    expect(mockedUpdateAnalysisReview).toHaveBeenCalledWith(analysisId, {
      review_status: 'changes_requested',
      review_note: 'Add evidence.',
      expected_version: 1,
    });
  });

  it('blocks empty changes-requested note locally', async () => {
    const user = userEvent.setup();
    mockedGetAnalysis.mockResolvedValue(analysis);
    renderDetail();

    await user.click(await screen.findByRole('button', { name: 'Request changes' }));

    expect(screen.getByRole('alert')).toHaveTextContent('meaningful review note');
    expect(mockedUpdateAnalysisReview).not.toHaveBeenCalled();
  });

  it('disables controls and blocks repeats while mutation is pending', async () => {
    const user = userEvent.setup();
    mockedGetAnalysis.mockResolvedValue(analysis);
    mockedUpdateAnalysisReview.mockReturnValue(new Promise(() => {}));
    renderDetail();

    const approve = await screen.findByRole('button', { name: 'Approve analysis' });
    await user.dblClick(approve);

    expect(mockedUpdateAnalysisReview).toHaveBeenCalledTimes(1);
    expect(approve).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Request changes' })).toBeDisabled();
    expect(screen.getByLabelText(/Review note/i)).toBeDisabled();
    expect(screen.getByText('Saving review').closest('[role="status"]')).toHaveAttribute('aria-live', 'polite');
  });

  it('updates saved review state only after server success and announces it', async () => {
    const user = userEvent.setup();
    let resolveReview!: (value: {
      analysis_id: string;
      review_status: 'approved';
      review_note: string;
      reviewed_at: string;
      review_version: number;
    }) => void;
    mockedGetAnalysis.mockResolvedValue(analysis);
    mockedUpdateAnalysisReview.mockReturnValue(new Promise((resolve) => {
      resolveReview = resolve;
    }));
    renderDetail();

    await user.type(await screen.findByLabelText(/Review note/i), 'Approved note');
    await user.click(screen.getByRole('button', { name: 'Approve analysis' }));
    expect(screen.getByText('Current status: pending review')).toBeInTheDocument();

    resolveReview({
      analysis_id: analysisId,
      review_status: 'approved',
      review_note: 'Approved note',
      reviewed_at: '2026-01-02T12:00:00Z',
      review_version: 2,
    });

    expect(await screen.findByText('Current status: approved')).toBeInTheDocument();
    expect(screen.getByText('Analysis review saved as approved.')).toHaveAttribute('role', 'status');
    expect(screen.getByDisplayValue('Approved note')).toBeInTheDocument();
  });

  it('retains saved state and sanitizes normal mutation errors', async () => {
    const user = userEvent.setup();
    mockedGetAnalysis.mockResolvedValue(analysis);
    mockedUpdateAnalysisReview.mockRejectedValue(new Error('raw server detail'));
    renderDetail();

    await user.click(await screen.findByRole('button', { name: 'Approve analysis' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('could not be saved');
    expect(screen.getByText('Current status: pending review')).toBeInTheDocument();
    expect(screen.queryByText('raw server detail')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve analysis' })).toBeEnabled();
  });

  it('shows conflict guidance and reloads current review state', async () => {
    const user = userEvent.setup();
    const refreshed = {
      ...analysis,
      review_status: 'changes_requested' as const,
      review_note: 'Current saved note.',
      reviewed_at: '2026-01-03T12:00:00Z',
      review_version: 3,
    };
    mockedGetAnalysis
      .mockResolvedValueOnce(analysis)
      .mockResolvedValueOnce(refreshed);
    mockedUpdateAnalysisReview.mockRejectedValue(new AnalysisReviewConflictError());
    renderDetail();

    await user.click(await screen.findByRole('button', { name: 'Approve analysis' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('changed elsewhere');

    await user.click(screen.getByRole('button', { name: 'Reload saved analysis' }));

    expect(mockedGetAnalysis).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('Current status: changes requested')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Current saved note.')).toBeInTheDocument();
    expect(screen.queryByText('changed elsewhere')).not.toBeInTheDocument();
  });

  it('disables review controls during conflict reload', async () => {
    const user = userEvent.setup();
    let resolveReload!: (value: PersistedAnalysisResponse) => void;
    mockedGetAnalysis
      .mockResolvedValueOnce(analysis)
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveReload = resolve;
      }));
    mockedUpdateAnalysisReview.mockRejectedValue(new AnalysisReviewConflictError());
    renderDetail();

    await user.click(await screen.findByRole('button', { name: 'Approve analysis' }));
    await user.click(await screen.findByRole('button', { name: 'Reload saved analysis' }));

    expect(screen.getByRole('button', { name: 'Approve analysis' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Request changes' })).toBeDisabled();
    expect(screen.getByLabelText(/Review note/i)).toBeDisabled();

    resolveReload(analysis);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve analysis' })).toBeEnabled());
  });
});
