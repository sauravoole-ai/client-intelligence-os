import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ActionStatusConflictError, getAction, listActions, listWorkspaceMembers, updateActionFollowUp, updateActionStatus } from '../services/api';
import type { ActionItem, ActionQueue } from '../types';
import ActionsPage from './ActionsPage';
import ActionItemCard from '../components/ActionItemCard';

vi.mock('../services/api', () => ({
  listActions: vi.fn(),
  listWorkspaceMembers: vi.fn(),
  updateActionFollowUp: vi.fn(),
  updateActionStatus: vi.fn(),
  getAction: vi.fn(),
  ActionStatusConflictError: class extends Error {},
}));

const mockedList = vi.mocked(listActions);
const mockedMembers = vi.mocked(listWorkspaceMembers);
const mockedFollowUp = vi.mocked(updateActionFollowUp);
const mockedStatus = vi.mocked(updateActionStatus);
const mockedGetAction = vi.mocked(getAction);
const action: ActionItem = {
  id: 'item-1', analysis_id: 'analysis-1', client_id: null, source_action_id: 'source-1',
  title: 'Follow up with client', description: 'Persisted operational rationale', priority: 1,
  status: 'open', linked_finding_ids: ['finding-1'], due_at: '2026-09-05T09:30:00+05:30',
  completed_at: null, assignee_membership_id: 'member-1', completion_outcome: null,
  assignee: { membership_id: 'member-1', display_name: 'Ada Lovelace', email: 'ada@example.test', role: 'member', status: 'active' },
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z', version: 1,
};
const renderPage = () => render(<MemoryRouter><ActionsPage /></MemoryRouter>);
const queues: Array<[ActionQueue, string]> = [
  ['open', 'Open'], ['due_today', 'Due today'], ['overdue', 'Overdue'],
  ['upcoming', 'Upcoming'], ['completed', 'Completed'], ['no_due_date', 'No due date'],
];

beforeEach(() => {
  vi.clearAllMocks();
  mockedList.mockResolvedValue({ items: [action], offset: 0, limit: 100, returned_count: 1 });
  mockedMembers.mockResolvedValue({ items: [{ membership_id: 'member-1', display_name: 'Ada Lovelace', email: 'ada@example.test', role: 'member' }, { membership_id: 'member-2', display_name: null, email: 'grace@example.test', role: 'member' }] });
  mockedFollowUp.mockResolvedValue(action);
  mockedStatus.mockResolvedValue(action);
});

describe('ActionsPage', () => {
  it('starts in the preserved unfiltered view and exposes every operational queue', async () => {
    renderPage();
    expect(screen.getByRole('button', { name: 'All Action Items' })).toHaveAttribute('aria-pressed', 'true');
    for (const [, label] of queues) expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    await waitFor(() => expect(mockedList).toHaveBeenCalledWith({ limit: 100 }));
  });

  it.each(queues)('requests the %s queue when %s is selected', async (queue, label) => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: label }));
    await waitFor(() => expect(mockedList).toHaveBeenLastCalledWith({ queue, limit: 100 }));
    expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows loading instead of an empty result until the selected queue resolves', async () => {
    let resolve!: (value: { items: ActionItem[]; offset: number; limit: number; returned_count: number }) => void;
    mockedList.mockReturnValue(new Promise((done) => { resolve = done; }));
    renderPage();
    expect(screen.getByRole('status')).toHaveTextContent('Loading Action Items');
    expect(screen.queryByText('No Action Items')).not.toBeInTheDocument();
    resolve({ items: [action], offset: 0, limit: 100, returned_count: 1 });
    expect(await screen.findByText(action.title)).toBeInTheDocument();
  });

  it('shows a queue-specific empty result without an error', async () => {
    mockedList.mockResolvedValue({ items: [], offset: 0, limit: 100, returned_count: 0 });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'No due date' }));
    expect(await screen.findByText(/No Action Items without a due date/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows a recoverable error instead of treating a failed queue as empty', async () => {
    mockedList.mockRejectedValueOnce(new Error('Safe failure')).mockResolvedValueOnce({ items: [], offset: 0, limit: 100, returned_count: 0 });
    renderPage();
    const user = userEvent.setup();
    expect(await screen.findByRole('alert')).toHaveTextContent('Action queue unavailable');
    expect(screen.queryByText('No Action Items')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No Action Items')).toBeInTheDocument();
  });

  it('renders the authoritative response as an editable operational scan surface', async () => {
    renderPage();
    expect(await screen.findByText(action.title)).toBeInTheDocument();
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('Due', { selector: 'dt' })).toBeInTheDocument();
    expect(screen.getByText('Source analysis')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit follow-up' })).toBeInTheDocument();
  });

  it('loads active members only when the human opens the follow-up editor and saves both nullable fields atomically', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Edit follow-up' }));
    expect(mockedMembers).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('Assignee')).toHaveValue('member-1');
    expect(screen.getByRole('option', { name: 'Unassigned' })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Assignee'), '');
    await user.clear(screen.getByLabelText('Due date and time'));
    await user.click(screen.getByRole('button', { name: 'Save follow-up' }));
    expect(mockedFollowUp).toHaveBeenCalledWith('item-1', { assignee_membership_id: null, due_at: null, expected_version: 1 });
  });

  it('places an existing aware due instant into the real local datetime editor input', async () => {
    const user = userEvent.setup();
    const aware = { ...action, due_at: '2026-09-05T04:30:00Z' };
    const date = new Date(aware.due_at);
    const part = (value: number) => String(value).padStart(2, '0');
    const expected = `${date.getFullYear()}-${part(date.getMonth() + 1)}-${part(date.getDate())}T${part(date.getHours())}:${part(date.getMinutes())}`;
    mockedList.mockResolvedValue({ items: [aware], offset: 0, limit: 100, returned_count: 1 });
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Edit follow-up' }));
    expect(screen.getByLabelText('Due date and time')).toHaveValue(expected);
  });

  it('sends an active reassignment together with the current complete due value', async () => {
    const user = userEvent.setup();
    const reassigned = { ...action, assignee_membership_id: 'member-2', assignee: { membership_id: 'member-2', display_name: null, email: 'grace@example.test', role: 'member' as const, status: 'active' as const }, version: 2 };
    mockedFollowUp.mockResolvedValue(reassigned);
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Edit follow-up' }));
    await user.selectOptions(screen.getByLabelText('Assignee'), 'member-2');
    await user.click(screen.getByRole('button', { name: 'Save follow-up' }));
    expect(mockedFollowUp).toHaveBeenCalledWith('item-1', { assignee_membership_id: 'member-2', due_at: new Date(action.due_at!).toISOString(), expected_version: 1 });
  });

  it('saves a non-null assignee and non-null due instant together in one follow-up PUT', async () => {
    const user = userEvent.setup();
    const due = '2026-09-06T10:15';
    const updated = { ...action, assignee_membership_id: 'member-2', due_at: new Date(due).toISOString(), version: 2 };
    mockedFollowUp.mockResolvedValue(updated);
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Edit follow-up' }));
    await user.selectOptions(screen.getByLabelText('Assignee'), 'member-2');
    fireEvent.change(screen.getByLabelText('Due date and time'), { target: { value: due } });
    await user.click(screen.getByRole('button', { name: 'Save follow-up' }));
    expect(mockedFollowUp).toHaveBeenCalledTimes(1);
    expect(mockedFollowUp).toHaveBeenCalledWith('item-1', { assignee_membership_id: 'member-2', due_at: new Date(due).toISOString(), expected_version: 1 });
  });

  it('keeps a follow-up draft open after a validation failure', async () => {
    const user = userEvent.setup();
    mockedFollowUp.mockRejectedValue(new Error('The Action Item request could not be validated.'));
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Edit follow-up' }));
    await user.selectOptions(screen.getByLabelText('Assignee'), 'member-2');
    await user.click(screen.getByRole('button', { name: 'Save follow-up' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be validated');
    expect(screen.getByLabelText('Assignee')).toHaveValue('member-2');
    expect(screen.queryByText('Follow-up saved.')).not.toBeInTheDocument();
  });

  it('does not claim success when a follow-up save returns the generic unavailable error', async () => {
    const user = userEvent.setup();
    mockedFollowUp.mockRejectedValue(new Error('The requested Action Item was not found.'));
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Edit follow-up' }));
    await user.selectOptions(screen.getByLabelText('Assignee'), 'member-2');
    await user.click(screen.getByRole('button', { name: 'Save follow-up' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('not found');
    expect(screen.getByLabelText('Assignee')).toHaveValue('member-2');
    expect(screen.queryByText('Follow-up saved.')).not.toBeInTheDocument();
  });

  it('requires a human outcome before an explicit completion request', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(action.title);
    await user.selectOptions(screen.getByLabelText('Status'), 'completed');
    await user.click(screen.getByRole('button', { name: 'Complete Action' }));
    expect(mockedStatus).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a completion outcome');
    await user.type(screen.getByLabelText(/Completion outcome/), 'Confirmed next steps with the client.');
    await user.click(screen.getByRole('button', { name: 'Complete Action' }));
    expect(mockedStatus).toHaveBeenCalledWith('item-1', { status: 'completed', completion_outcome: 'Confirmed next steps with the client.', expected_version: 1 });
  });

  it('retains a disabled historical assignee when only the due date changes', async () => {
    const user = userEvent.setup();
    const disabled = { ...action, assignee_membership_id: 'former-member', assignee: { membership_id: 'former-member', display_name: null, email: 'former@example.test', role: 'member' as const, status: 'disabled' as const } };
    mockedList.mockResolvedValue({ items: [disabled], offset: 0, limit: 100, returned_count: 1 });
    mockedFollowUp.mockResolvedValue(disabled);
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Edit follow-up' }));
    expect(screen.getByRole('option', { name: 'former@example.test (inactive)' })).toBeInTheDocument();
    const local = '2026-09-06T10:15';
    fireEvent.change(screen.getByLabelText('Due date and time'), { target: { value: local } });
    await user.click(screen.getByRole('button', { name: 'Save follow-up' }));
    expect(mockedFollowUp).toHaveBeenCalledWith('item-1', { assignee_membership_id: 'former-member', due_at: new Date(local).toISOString(), expected_version: 1 });
  });

  it('refetches authoritative state after a stale follow-up conflict without retrying', async () => {
    const user = userEvent.setup();
    const latest = { ...action, due_at: '2026-09-07T09:30:00+05:30', version: 2 };
    mockedFollowUp.mockRejectedValue(new ActionStatusConflictError());
    mockedGetAction.mockResolvedValue(latest);
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Edit follow-up' }));
    fireEvent.change(screen.getByLabelText('Due date and time'), { target: { value: '2026-09-06T10:15' } });
    await user.click(screen.getByRole('button', { name: 'Save follow-up' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('changed elsewhere');
    await waitFor(() => expect(mockedGetAction).toHaveBeenCalledWith('item-1'));
    expect(mockedFollowUp).toHaveBeenCalledTimes(1);
  });

  it('replaces a stale follow-up draft with the refetched baseline and uses its version on the next explicit save', async () => {
    const user = userEvent.setup();
    const latest = { ...action, assignee_membership_id: 'member-2', assignee: { membership_id: 'member-2', display_name: null, email: 'grace@example.test', role: 'member' as const, status: 'active' as const }, due_at: '2026-09-08T09:30:00+05:30', version: 2 };
    mockedList.mockResolvedValueOnce({ items: [action], offset: 0, limit: 100, returned_count: 1 }).mockResolvedValue({ items: [latest], offset: 0, limit: 100, returned_count: 1 });
    mockedFollowUp.mockRejectedValueOnce(new ActionStatusConflictError()).mockResolvedValueOnce(latest);
    mockedGetAction.mockResolvedValue(latest);
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Edit follow-up' }));
    fireEvent.change(screen.getByLabelText('Due date and time'), { target: { value: '2026-09-06T10:15' } });
    await user.click(screen.getByRole('button', { name: 'Save follow-up' }));
    await waitFor(() => expect(screen.getByText('grace@example.test')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Edit follow-up' }));
    expect(screen.getByLabelText('Assignee')).toHaveValue('member-2');
    fireEvent.change(screen.getByLabelText('Due date and time'), { target: { value: '2026-09-09T10:15' } });
    await user.click(screen.getByRole('button', { name: 'Save follow-up' }));
    expect(mockedFollowUp).toHaveBeenCalledTimes(2);
    expect(mockedFollowUp).toHaveBeenLastCalledWith('item-1', { assignee_membership_id: 'member-2', due_at: new Date('2026-09-09T10:15').toISOString(), expected_version: 2 });
  });

  it('uses the authoritative completion state after a stale completion conflict without retrying', async () => {
    const user = userEvent.setup();
    const latest = { ...action, status: 'in_progress' as const, version: 2 };
    mockedStatus.mockRejectedValue(new ActionStatusConflictError());
    mockedGetAction.mockResolvedValue(latest);
    renderPage();
    await screen.findByText(action.title);
    await user.selectOptions(screen.getByLabelText('Status'), 'completed');
    await user.type(screen.getByLabelText(/Completion outcome/), 'Human completion');
    await user.click(screen.getByRole('button', { name: 'Complete Action' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('changed elsewhere');
    expect(mockedStatus).toHaveBeenCalledTimes(1);
    expect(mockedGetAction).toHaveBeenCalledWith('item-1');
  });

  it('replaces a stale completion attempt with the refetched baseline and uses its version on the next explicit completion', async () => {
    const user = userEvent.setup();
    const latest = { ...action, status: 'in_progress' as const, version: 2 };
    const completed = { ...latest, status: 'completed' as const, completion_outcome: 'Reviewed after conflict', completed_at: '2026-09-08T04:00:00Z', version: 3 };
    mockedList.mockResolvedValueOnce({ items: [action], offset: 0, limit: 100, returned_count: 1 }).mockResolvedValue({ items: [latest], offset: 0, limit: 100, returned_count: 1 });
    mockedStatus.mockRejectedValueOnce(new ActionStatusConflictError()).mockResolvedValueOnce(completed);
    mockedGetAction.mockResolvedValue(latest);
    renderPage();
    await screen.findByText(action.title);
    await user.selectOptions(screen.getByLabelText('Status'), 'completed');
    await user.type(screen.getByLabelText(/Completion outcome/), 'Stale outcome');
    await user.click(screen.getByRole('button', { name: 'Complete Action' }));
    await waitFor(() => expect(screen.getByLabelText('Status')).toHaveValue('in_progress'));
    await user.selectOptions(screen.getByLabelText('Status'), 'completed');
    await user.type(screen.getByLabelText(/Completion outcome/), 'Reviewed after conflict');
    await user.click(screen.getByRole('button', { name: 'Complete Action' }));
    expect(mockedStatus).toHaveBeenCalledTimes(2);
    expect(mockedStatus).toHaveBeenLastCalledWith('item-1', { status: 'completed', completion_outcome: 'Reviewed after conflict', expected_version: 2 });
  });

  it('preserves an unsaved follow-up draft when an equivalent Action object rerenders at the same version', async () => {
    function Harness() { const [current, setCurrent] = useState(action); return <><button type="button" onClick={() => setCurrent({ ...current })}>Rerender action</button><ActionItemCard action={current} onChange={() => undefined} /></>; }
    const user = userEvent.setup();
    render(<MemoryRouter><Harness /></MemoryRouter>);
    await user.click(screen.getByRole('button', { name: 'Edit follow-up' }));
    await user.selectOptions(screen.getByLabelText('Assignee'), 'member-2');
    await user.click(screen.getByRole('button', { name: 'Rerender action' }));
    expect(screen.getByLabelText('Assignee')).toHaveValue('member-2');
    expect(mockedFollowUp).not.toHaveBeenCalled();
  });

  it('keeps a locally valid completion draft after the server rejects it', async () => {
    const user = userEvent.setup();
    mockedStatus.mockRejectedValue(new Error('The Action Item request could not be validated.'));
    renderPage();
    await screen.findByText(action.title);
    await user.selectOptions(screen.getByLabelText('Status'), 'completed');
    await user.type(screen.getByLabelText(/Completion outcome/), 'Valid human outcome');
    await user.click(screen.getByRole('button', { name: 'Complete Action' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be validated');
    expect(screen.getByLabelText('Status')).toHaveValue('completed');
    expect(screen.getByLabelText(/Completion outcome/)).toHaveValue('Valid human outcome');
    expect(screen.getByText('open', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.queryByText('Action Item completed.')).not.toBeInTheDocument();
  });

  it('uses the returned outcome and completed timestamp after an explicit completed-outcome edit', async () => {
    const user = userEvent.setup();
    const completed = { ...action, status: 'completed' as const, completion_outcome: 'Outcome X', completed_at: '2026-09-05T05:00:00Z', version: 2 };
    const updated = { ...completed, completion_outcome: 'Outcome Y', version: 3 };
    mockedList.mockResolvedValueOnce({ items: [completed], offset: 0, limit: 100, returned_count: 1 }).mockResolvedValue({ items: [updated], offset: 0, limit: 100, returned_count: 1 });
    mockedStatus.mockResolvedValue(updated);
    renderPage();
    await user.clear(await screen.findByLabelText(/Completion outcome/));
    await user.type(screen.getByLabelText(/Completion outcome/), 'Outcome Y');
    await user.click(screen.getByRole('button', { name: 'Complete Action' }));
    await waitFor(() => expect(screen.getByLabelText('Status')).toHaveValue('completed'));
    expect(screen.getByLabelText(/Completion outcome/)).toHaveValue('Outcome Y');
    expect(screen.getByText('Completed', { selector: 'dt' })).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Outcome X')).not.toBeInTheDocument();
  });

  it('uses backend cleanup and synchronizes controls after an explicit reopen transition', async () => {
    const user = userEvent.setup();
    const completed = { ...action, status: 'completed' as const, completion_outcome: 'Outcome X', completed_at: '2026-09-05T05:00:00Z', version: 2 };
    const reopened = { ...completed, status: 'open' as const, completion_outcome: null, completed_at: null, version: 3 };
    mockedList.mockResolvedValueOnce({ items: [completed], offset: 0, limit: 100, returned_count: 1 }).mockResolvedValue({ items: [reopened], offset: 0, limit: 100, returned_count: 1 });
    mockedStatus.mockResolvedValue(reopened);
    renderPage();
    await user.selectOptions(await screen.findByLabelText('Status'), 'open');
    await user.click(screen.getByRole('button', { name: 'Save status' }));
    expect(mockedStatus).toHaveBeenCalledWith('item-1', { status: 'open', completion_outcome: null, expected_version: 2 });
    await waitFor(() => expect(screen.getByLabelText('Status')).toHaveValue('open'));
    expect(screen.queryByLabelText(/Completion outcome/)).not.toBeInTheDocument();
    expect(screen.queryByText('Completed', { selector: 'dt' })).not.toBeInTheDocument();
  });

  const newYorkRuntime = Intl.DateTimeFormat().resolvedOptions().timeZone === 'America/New_York';
  it.skipIf(!newYorkRuntime)('rejects a nonexistent New York DST-gap value through the real follow-up editor', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Edit follow-up' }));
    fireEvent.change(screen.getByLabelText('Due date and time'), { target: { value: '2026-03-08T02:30' } });
    await user.click(screen.getByRole('button', { name: 'Save follow-up' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a valid local date and time');
    expect(mockedFollowUp).not.toHaveBeenCalled();
  });
});
