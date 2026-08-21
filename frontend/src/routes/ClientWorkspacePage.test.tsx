import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getClient, listClientActions, listClientAnalyses } from '../services/api';
import type { ActionItem, Client, PersistedAnalysisResponse } from '../types';
import ClientWorkspacePage from './ClientWorkspacePage';

vi.mock('../services/api', () => ({ getClient: vi.fn(), listClientAnalyses: vi.fn(), listClientActions: vi.fn(), updateActionStatus: vi.fn(), getAction: vi.fn(), ActionStatusConflictError: class extends Error {} }));
const mockedGet = vi.mocked(getClient); const mockedAnalyses = vi.mocked(listClientAnalyses); const mockedActions = vi.mocked(listClientActions);
const client: Client = { id: 'client-1', display_name: 'Ada Client', external_reference: 'ADA-1', status: 'active', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z' };
const finding = { finding_id: 'f1', category: 'sleep', title: 'Sleep', statement: 'Structured finding', classification: 'client_reported_information', confidence: 0.9, evidence: [], review_status: 'pending' as const };
const analysis: PersistedAnalysisResponse = { analysis_id: 'analysis-1', client_id: client.id, status: 'completed', created_at: '2026-01-03T00:00:00Z', client_reference: 'ADA-1', analysis_period: 'Week 1', weekly_summary: finding, findings: [finding], risk_flags: [], recommended_actions: [], missing_information: [], engine: 'deterministic', prompt_version: 'v1', validation_warnings: ['warning'], fallback_reason: null, review_status: 'approved', review_note: 'Reviewed safely', reviewed_at: '2026-01-04T00:00:00Z', review_version: 2 };
const action: ActionItem = { id: 'item-1', analysis_id: analysis.analysis_id, client_id: client.id, source_action_id: 'source-1', title: 'Client-specific follow-up', description: 'Stored rationale', priority: 1, status: 'in_progress', linked_finding_ids: [], due_at: null, completed_at: null, created_at: '2026-01-03T00:00:00Z', updated_at: '2026-01-04T00:00:00Z', version: 2 };
function renderPage() { return render(<MemoryRouter initialEntries={['/clients/client-1']}><Routes><Route path="/clients/:clientId" element={<ClientWorkspacePage />} /></Routes></MemoryRouter>); }
beforeEach(() => { vi.clearAllMocks(); mockedGet.mockResolvedValue(client); mockedAnalyses.mockResolvedValue({ items: [analysis], offset: 0, limit: 100, returned_count: 1 }); mockedActions.mockResolvedValue({ items: [], offset: 0, limit: 100, returned_count: 0 }); });

describe('ClientWorkspacePage', () => {
  it('shows loading while real data is pending', () => { mockedGet.mockReturnValue(new Promise(() => {})); mockedAnalyses.mockReturnValue(new Promise(() => {})); renderPage(); expect(screen.getByText(/Loading client workspace/)).toBeInTheDocument(); });
  it('renders client metadata and real analysis history with saved links', async () => { renderPage(); expect(await screen.findByText('Ada Client')).toBeInTheDocument(); expect(screen.getByText('ADA-1')).toBeInTheDocument(); expect(screen.getByText('Week 1')).toBeInTheDocument(); expect(screen.getByText('Reviewed safely')).toBeInTheDocument(); expect(screen.getByRole('link', { name: 'Open saved analysis' })).toHaveAttribute('href', '/analyses/analysis-1'); expect(screen.queryByText(/Coach|attention|Evidence trace/i)).not.toBeInTheDocument(); });
  it('shows a zero-analysis state', async () => { mockedAnalyses.mockResolvedValue({ items: [], offset: 0, limit: 100, returned_count: 0 }); renderPage(); expect(await screen.findByText('No linked analyses')).toBeInTheDocument(); });
  it('shows a missing client state', async () => { mockedGet.mockRejectedValue(new Error('The requested client was not found.')); renderPage(); expect(await screen.findByText('Client not found')).toBeInTheDocument(); });
  it('shows generic errors and retries', async () => { mockedGet.mockRejectedValueOnce(new Error('Safe failure')).mockResolvedValueOnce(client); renderPage(); const user = userEvent.setup(); await user.click(await screen.findByRole('button', { name: 'Retry' })); expect(await screen.findByText('Ada Client')).toBeInTheDocument(); });
  it('never renders original conversation or raw analysis output', async () => { renderPage(); await screen.findByText('Ada Client'); expect(document.body).not.toHaveTextContent('original conversation'); expect(document.body).not.toHaveTextContent('analysis_output'); });
  it('renders only real Client-scoped Action Items', async () => { mockedActions.mockResolvedValue({ items: [action], offset: 0, limit: 100, returned_count: 1 }); renderPage(); expect(await screen.findByText('Client-specific follow-up')).toBeInTheDocument(); expect(screen.getByText(/Priority 1/)).toBeInTheDocument(); expect(mockedActions).toHaveBeenCalledWith('client-1'); });
});
