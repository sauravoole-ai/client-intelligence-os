import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAnalysis } from '../services/api';
import type { AnalysisResponse } from '../types';
import NewAnalysisPage from './NewAnalysisPage';

vi.mock('../services/api', () => ({
  createAnalysis: vi.fn(),
}));

const mockedCreateAnalysis = vi.mocked(createAnalysis);
const analysisId = '00000000-0000-4000-8000-000000000001';
const validConversation = 'Client: This is a sufficiently long conversation update.';

const finding = {
  finding_id: 'finding-1',
  category: 'sleep',
  title: 'Sleep pattern',
  statement: 'The client reported short sleep.',
  classification: 'client_reported_information',
  confidence: 0.9,
  evidence: [],
  review_status: 'pending' as const,
};

const analysis: AnalysisResponse = {
  analysis_id: analysisId,
  status: 'completed',
  created_at: '2026-01-01T10:30:00Z',
  client_reference: 'ANON-001',
  analysis_period: 'Week 1',
  weekly_summary: finding,
  findings: [finding],
  risk_flags: [],
  recommended_actions: [],
  missing_information: [],
  engine: 'deterministic_evidence_baseline_v1',
  prompt_version: 'deterministic-baseline-v1',
  validation_warnings: [],
  fallback_reason: null,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <NewAnalysisPage />
    </MemoryRouter>,
  );
}

async function submitValidConversation() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Conversation text'), validConversation);
  await user.click(screen.getByRole('button', { name: 'Submit analysis' }));
  return user;
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('NewAnalysisPage submission workflow', () => {
  it('keeps the completed result summary visible after success', async () => {
    mockedCreateAnalysis.mockResolvedValue(analysis);
    renderPage();

    await submitValidConversation();

    expect(await screen.findByText('Completed')).toBeInTheDocument();
    expect(screen.getByText('ANON-001')).toBeInTheDocument();
    expect(screen.getByText('deterministic_evidence_baseline_v1')).toBeInTheDocument();
    expect(screen.getByText('Findings:').parentElement).toHaveTextContent('Findings: 1');
  });

  it('links to the saved analysis returned by the API', async () => {
    mockedCreateAnalysis.mockResolvedValue(analysis);
    renderPage();

    await submitValidConversation();

    expect(await screen.findByRole('link', { name: 'Open saved analysis' }))
      .toHaveAttribute('href', `/analyses/${analysisId}`);
  });

  it('links to the complete saved analyses list', async () => {
    mockedCreateAnalysis.mockResolvedValue(analysis);
    renderPage();

    await submitValidConversation();

    expect(await screen.findByRole('link', { name: 'View all analyses' }))
      .toHaveAttribute('href', '/analyses');
  });

  it('preserves the Anonymous client fallback', async () => {
    mockedCreateAnalysis.mockResolvedValue({ ...analysis, client_reference: null });
    renderPage();

    await submitValidConversation();

    expect(await screen.findByText('Anonymous')).toBeInTheDocument();
  });

  it('does not show success links before submission', () => {
    renderPage();

    expect(screen.queryByRole('link', { name: 'Open saved analysis' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'View all analyses' })).not.toBeInTheDocument();
  });

  it('does not show success links after an API failure', async () => {
    mockedCreateAnalysis.mockRejectedValue(new Error('The intelligence engine is currently unavailable.'));
    renderPage();

    await submitValidConversation();
    await screen.findByText('Submission issue');

    expect(screen.queryByRole('link', { name: 'Open saved analysis' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'View all analyses' })).not.toBeInTheDocument();
  });

  it('disables the submit button while the request is pending', async () => {
    mockedCreateAnalysis.mockReturnValue(new Promise(() => {}));
    renderPage();

    await submitValidConversation();

    expect(screen.getByRole('button', { name: /Submitting/i })).toBeDisabled();
  });

  it('disables all editable form controls while the request is pending', async () => {
    mockedCreateAnalysis.mockReturnValue(new Promise(() => {}));
    renderPage();

    await submitValidConversation();

    expect(screen.getByLabelText('Anonymised client reference')).toBeDisabled();
    expect(screen.getByLabelText('Analysis period')).toBeDisabled();
    expect(screen.getByLabelText('Conversation text')).toBeDisabled();
    expect(screen.getByRole('combobox')).toBeDisabled();
  });

  it('blocks repeated submission while the first request is pending', async () => {
    const user = userEvent.setup();
    mockedCreateAnalysis.mockReturnValue(new Promise(() => {}));
    renderPage();
    await user.type(screen.getByLabelText('Conversation text'), validConversation);

    const submit = screen.getByRole('button', { name: 'Submit analysis' });
    await user.dblClick(submit);

    expect(mockedCreateAnalysis).toHaveBeenCalledTimes(1);
  });

  it('prevents an undersized conversation from calling the API', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText('Conversation text'), 'Too short');

    expect(screen.getByRole('button', { name: 'Submit analysis' })).toBeDisabled();
    expect(mockedCreateAnalysis).not.toHaveBeenCalled();
  });

  it('renders sanitized API errors', async () => {
    mockedCreateAnalysis.mockRejectedValue(new Error('The submitted conversation could not be validated.'));
    renderPage();

    await submitValidConversation();

    expect(await screen.findByText('The submitted conversation could not be validated.')).toBeInTheDocument();
  });

  it('restores editable controls after failure', async () => {
    mockedCreateAnalysis.mockRejectedValue(new Error('The intelligence engine is currently unavailable.'));
    renderPage();

    await submitValidConversation();
    await waitFor(() => expect(screen.getByText('Submission issue')).toBeInTheDocument());

    expect(screen.getByLabelText('Conversation text')).toBeEnabled();
    expect(screen.getByRole('combobox')).toBeEnabled();
  });
});
