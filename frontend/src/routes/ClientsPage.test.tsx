import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ClientConflictError, createClient, listClients } from '../services/api';
import type { Client } from '../types';
import ClientsPage from './ClientsPage';

vi.mock('../services/api', () => ({
  listClients: vi.fn(),
  createClient: vi.fn(),
  ClientConflictError: class extends Error {
    constructor() { super('That external reference is already in use. Choose another reference.'); }
  },
}));
const mockedList = vi.mocked(listClients);
const mockedCreate = vi.mocked(createClient);
const active: Client = { id: 'client-1', display_name: 'Ada Client', external_reference: 'ADA-1', status: 'active', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z' };
const archived: Client = { ...active, id: 'client-2', display_name: 'Beta Client', external_reference: null, status: 'archived' };
const response = { items: [active, archived], offset: 0, limit: 100, returned_count: 2 };
const renderPage = () => render(<MemoryRouter><ClientsPage /></MemoryRouter>);

beforeEach(() => { vi.clearAllMocks(); mockedList.mockResolvedValue(response); });

describe('ClientsPage', () => {
  it('shows loading then renders real clients without fabricated metrics', async () => {
    mockedList.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText(/Loading the client directory/)).toBeInTheDocument();
    expect(screen.queryByText(/Coach|attention|next action/i)).not.toBeInTheDocument();
  });
  it('renders names, references, null references, status, and workspace links', async () => {
    renderPage();
    expect(await screen.findByText('Ada Client')).toBeInTheDocument();
    expect(screen.getByText('ADA-1')).toBeInTheDocument();
    expect(screen.getByText('No external reference')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Open workspace' })[0]).toHaveAttribute('href', '/clients/client-1');
  });
  it('filters by search and status', async () => {
    const user = userEvent.setup(); renderPage(); await screen.findByText('Ada Client');
    await user.type(screen.getByLabelText('Search client directory'), 'ADA-1');
    expect(screen.queryByText('Beta Client')).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText('Search client directory'));
    await user.selectOptions(screen.getByLabelText('Filter by status'), 'archived');
    expect(screen.getByText('Beta Client')).toBeInTheDocument(); expect(screen.queryByText('Ada Client')).not.toBeInTheDocument();
  });
  it('shows empty and retrieval error states with retry', async () => {
    mockedList.mockResolvedValueOnce({ items: [], offset: 0, limit: 100, returned_count: 0 }); renderPage();
    expect(await screen.findByText('No clients yet')).toBeInTheDocument();
  });
  it('retries a failed retrieval', async () => {
    mockedList.mockRejectedValueOnce(new Error('Safe failure')).mockResolvedValueOnce(response); renderPage();
    const user = userEvent.setup(); await user.click(await screen.findByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Ada Client')).toBeInTheDocument(); expect(mockedList).toHaveBeenCalledTimes(2);
  });
  it('creates a normalized client and blocks blank names', async () => {
    mockedCreate.mockResolvedValue(active); const user = userEvent.setup(); renderPage();
    await user.click(screen.getByRole('button', { name: 'New client' }));
    expect(screen.getByRole('button', { name: 'Create client' })).toBeDisabled();
    await user.type(screen.getByLabelText('Display name'), '  Ada Client  '); await user.type(screen.getByLabelText(/External reference/), ' ADA-1 ');
    await user.click(screen.getByRole('button', { name: 'Create client' }));
    await waitFor(() => expect(mockedCreate).toHaveBeenCalledWith({ display_name: 'Ada Client', external_reference: 'ADA-1' }));
    expect(await screen.findByRole('status')).toHaveTextContent('was added');
  });
  it('disables creation while pending and exposes conflict feedback', async () => {
    mockedCreate.mockReturnValueOnce(new Promise(() => {})); const user = userEvent.setup(); renderPage(); await user.click(screen.getByRole('button', { name: 'New client' })); await user.type(screen.getByLabelText('Display name'), 'Ada'); await user.click(screen.getByRole('button', { name: 'Create client' })); expect(screen.getByRole('button', { name: 'Creating…' })).toBeDisabled();
  });
  it('renders an accessible duplicate conflict', async () => {
    mockedCreate.mockRejectedValue(new ClientConflictError()); const user = userEvent.setup(); renderPage(); await user.click(screen.getByRole('button', { name: 'New client' })); await user.type(screen.getByLabelText('Display name'), 'Ada'); await user.click(screen.getByRole('button', { name: 'Create client' })); expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});
