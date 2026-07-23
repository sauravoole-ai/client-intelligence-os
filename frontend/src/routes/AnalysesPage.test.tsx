import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { listAnalyses } from '../services/api';
import type { AnalysisListResponse, AnalysisResponse } from '../types';
import AnalysesPage from './AnalysesPage';

vi.mock('../services/api', () => ({
  listAnalyses: vi.fn(),
}));

const mockedListAnalyses = vi.mocked(listAnalyses);

const finding = {
  finding_id: 'finding-1',
  category: 'sleep',
  title: 'Sleep',
  statement: 'The client reported short sleep.',
  classification: 'client_reported_information',
  confidence: 0.9,
  evidence: [],
  review_status: 'pending' as const,
};

const analysis: AnalysisResponse = {
  analysis_id: '00000000-0000-0000-0000-000000000001',
  status: 'completed',
  created_at: '2026-01-01T10:30:00Z',
  client_reference: 'ANON-001',
  analysis_period: 'Week 1',
  weekly_summary: finding,
  findings: [finding, { ...finding, finding_id: 'finding-2' }],
  risk_flags: [{
    risk_id: 'risk-1',
    title: 'Fatigue',
    severity: 'high',
    rationale: 'Follow-up required.',
    classification: 'ai_generated_inference',
    confidence: 0.8,
    evidence: [],
    review_status: 'pending',
  }],
  recommended_actions: [{
    action_id: 'action-1',
    priority: 1,
    action: 'Follow up.',
    rationale: 'Fatigue was reported.',
    classification: 'ai_generated_inference',
    linked_finding_ids: ['finding-1'],
    evidence: [],
    review_status: 'pending',
  }],
  missing_information: [],
  engine: 'deterministic_evidence_baseline_v1',
  prompt_version: 'deterministic-baseline-v1',
  validation_warnings: ['Review fallback output.'],
  fallback_reason: 'llm_not_configured',
};

function response(items: AnalysisResponse[]): AnalysisListResponse {
  return { items, offset: 0, limit: 20, returned_count: items.length };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AnalysesPage />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('AnalysesPage', () => {
  it('announces its loading state', () => {
    mockedListAnalyses.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(screen.getByRole('status')).toHaveTextContent('Loading saved analyses');
  });

  it('renders a populated response and returned count', async () => {
    mockedListAnalyses.mockResolvedValue(response([analysis]));
    renderPage();

    expect(await screen.findByText('ANON-001')).toBeInTheDocument();
    expect(screen.getByText('1', { selector: '.analyses-page__count strong' })).toBeInTheDocument();
  });

  it('renders the anonymised client reference', async () => {
    mockedListAnalyses.mockResolvedValue(response([analysis]));
    renderPage();

    expect(await screen.findByRole('heading', { name: 'ANON-001' })).toBeInTheDocument();
  });

  it('uses Anonymous when the client reference is absent', async () => {
    mockedListAnalyses.mockResolvedValue(response([{ ...analysis, client_reference: null }]));
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Anonymous' })).toBeInTheDocument();
  });

  it('renders finding, risk and action counts', async () => {
    mockedListAnalyses.mockResolvedValue(response([analysis]));
    renderPage();
    await screen.findByText('ANON-001');

    expect(screen.getByText('Findings').nextElementSibling).toHaveTextContent('2');
    expect(screen.getByText('Risk flags').nextElementSibling).toHaveTextContent('1');
    expect(screen.getByText('Actions').nextElementSibling).toHaveTextContent('1');
  });

  it('renders fallback and warning statuses', async () => {
    mockedListAnalyses.mockResolvedValue(response([analysis]));
    renderPage();

    expect(await screen.findByText('Fallback used: llm_not_configured')).toBeInTheDocument();
    expect(screen.getByText('1 validation warning')).toBeInTheDocument();
  });

  it('renders a meaningful empty state', async () => {
    mockedListAnalyses.mockResolvedValue(response([]));
    renderPage();

    expect(await screen.findByRole('heading', { name: 'No saved analyses yet' })).toBeInTheDocument();
  });

  it('renders a sanitized error without raw details', async () => {
    mockedListAnalyses.mockRejectedValue(new Error('raw database detail'));
    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent('temporarily unavailable');
    expect(screen.queryByText('raw database detail')).not.toBeInTheDocument();
  });

  it('retries the request after an error', async () => {
    const user = userEvent.setup();
    mockedListAnalyses
      .mockRejectedValueOnce(new Error('network detail'))
      .mockResolvedValueOnce(response([]));
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(mockedListAnalyses).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('heading', { name: 'No saved analyses yet' })).toBeInTheDocument();
  });

  it('links to the matching analysis ID', async () => {
    mockedListAnalyses.mockResolvedValue(response([analysis]));
    renderPage();

    expect(await screen.findByRole('link', { name: 'Open analysis for ANON-001' }))
      .toHaveAttribute('href', `/analyses/${analysis.analysis_id}`);
  });

  it('never renders an original conversation field', async () => {
    const recordWithConversation = {
      ...analysis,
      conversation: 'PRIVATE ORIGINAL CONVERSATION',
    } as AnalysisResponse;
    mockedListAnalyses.mockResolvedValue(response([recordWithConversation]));
    renderPage();

    await screen.findByText('ANON-001');
    expect(screen.queryByText('PRIVATE ORIGINAL CONVERSATION')).not.toBeInTheDocument();
  });

  it('requests the first page with the fixed slice size', async () => {
    mockedListAnalyses.mockResolvedValue(response([]));
    renderPage();

    await waitFor(() => expect(mockedListAnalyses).toHaveBeenCalledWith({ offset: 0, limit: 20 }));
  });

  it('adds Analyses to primary navigation', () => {
    mockedListAnalyses.mockResolvedValue(response([]));
    render(
      <MemoryRouter initialEntries={['/overview']}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole('link', { name: /Analyses/i })).toHaveAttribute('href', '/analyses');
  });
});
