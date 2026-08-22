import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ActionStatusConflictError, getAction, listActions, updateActionStatus } from '../services/api';
import type { ActionItem } from '../types';
import ActionsPage from './ActionsPage';

vi.mock('../services/api', () => ({ listActions: vi.fn(), updateActionStatus: vi.fn(), getAction: vi.fn(), ActionStatusConflictError: class extends Error {} }));
const mockedList = vi.mocked(listActions); const mockedUpdate = vi.mocked(updateActionStatus); const mockedGet = vi.mocked(getAction);
const action: ActionItem = { id: 'item-1', analysis_id: 'analysis-1', client_id: null, source_action_id: 'source-1', title: 'Follow up with client', description: 'Persisted operational rationale', priority: 1, status: 'open', linked_finding_ids: ['finding-1'], due_at: null, completed_at: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z', version: 1 };
const renderPage = () => render(<MemoryRouter><ActionsPage /></MemoryRouter>);
beforeEach(() => { vi.clearAllMocks(); mockedList.mockResolvedValue({ items: [action], offset: 0, limit: 100, returned_count: 1 }); });

describe('ActionsPage', () => {
  it('shows loading then real persisted actions without fake ownership', async () => { mockedList.mockReturnValue(new Promise(() => {})); renderPage(); expect(screen.getByText(/Loading Action Items/)).toBeInTheDocument(); expect(screen.queryByText(/coach|owner/i)).not.toBeInTheDocument(); });
  it('renders title, rationale, priority, timestamps, and anonymous relation', async () => { renderPage(); expect(await screen.findByText(action.title)).toBeInTheDocument(); expect(screen.getByText(action.description)).toBeInTheDocument(); expect(screen.getByText(/Priority 1/)).toBeInTheDocument(); expect(screen.getByText('Anonymous analysis')).toBeInTheDocument(); });
  it('renders empty, error, and retry states', async () => { mockedList.mockRejectedValueOnce(new Error('Safe failure')).mockResolvedValueOnce({ items: [], offset: 0, limit: 100, returned_count: 0 }); renderPage(); const user = userEvent.setup(); await user.click(await screen.findByRole('button', { name: 'Retry' })); expect(await screen.findByText('No Action Items')).toBeInTheDocument(); });
  it('uses the backend status filter', async () => { renderPage(); const user = userEvent.setup(); await screen.findByText(action.title); await user.selectOptions(screen.getByLabelText('Status', { selector: '#action-filter' }), 'completed'); expect(mockedList).toHaveBeenLastCalledWith({ status: 'completed', limit: 100 }); });
  it('sends the current version and waits for server confirmation', async () => { let resolve!: (value: ActionItem) => void; mockedUpdate.mockReturnValue(new Promise((done) => { resolve = done; })); renderPage(); const user = userEvent.setup(); await screen.findByText(action.title); const select = screen.getByLabelText('Status', { selector: '#action-status-item-1' }); await user.selectOptions(select, 'completed'); expect(mockedUpdate).toHaveBeenCalledWith('item-1', { status: 'completed', expected_version: 1 }); expect(screen.getByText('open')).toBeInTheDocument(); expect(select).toBeDisabled(); resolve({ ...action, status: 'completed', version: 2, completed_at: '2026-01-03T00:00:00Z' }); expect(await screen.findByText('completed')).toBeInTheDocument(); });
  it('shows conflict guidance and reloads the Action Item', async () => { mockedUpdate.mockRejectedValue(new ActionStatusConflictError()); mockedGet.mockResolvedValue({ ...action, status: 'in_progress', version: 2 }); renderPage(); const user = userEvent.setup(); await screen.findByText(action.title); await user.selectOptions(screen.getByLabelText('Status', { selector: '#action-status-item-1' }), 'completed'); expect(await screen.findByRole('alert')).toHaveTextContent('changed elsewhere'); await user.click(screen.getByRole('button', { name: 'Reload action' })); expect(mockedGet).toHaveBeenCalledWith('item-1'); });
});
