import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getAnalysis } from '../services/api';
import type { AnalysisResponse } from '../types';
import AnalysisDetailPage from './AnalysisDetailPage';

vi.mock('../services/api', () => ({
  getAnalysis: vi.fn(),
}));

const mockedGetAnalysis = vi.mocked(getAnalysis);
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

const analysis: AnalysisResponse = {
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
    } as AnalysisResponse);
    renderDetail();

    await screen.findByRole('heading', { name: 'ANON-001' });
    expect(screen.queryByText('PRIVATE ORIGINAL CONVERSATION')).not.toBeInTheDocument();
  });

  it('handles a malformed route ID without requesting data', async () => {
    renderDetail('/analyses/not-a-uuid');

    expect(await screen.findByRole('heading', { name: 'Invalid analysis link' })).toBeInTheDocument();
    expect(mockedGetAnalysis).not.toHaveBeenCalled();
  });
});
