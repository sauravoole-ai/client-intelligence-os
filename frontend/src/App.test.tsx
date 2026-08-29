import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const session = {
  user_id: 'user-1',
  display_name: 'Ada Lovelace',
  email: 'ada@example.com',
  workspace_id: 'workspace-1',
  workspace_name: 'Atlas Coaching',
  role: 'owner',
  csrf_token: 'csrf-for-this-session',
};

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(session), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('application shell', () => {
  it('renders the overview page by default', async () => {
    const view = render(
      <MemoryRouter initialEntries={['/overview']}>
        <App />
      </MemoryRouter>,
    );

    expect(await view.findByText(/Operational overview/i)).toBeInTheDocument();
  });

  it('opens the intelligence navigator from the shell', async () => {
    const user = userEvent.setup();
    const view = render(
      <MemoryRouter initialEntries={['/overview']}>
        <App />
      </MemoryRouter>,
    );

    await screen.findByText(/Operational overview/i);
    await user.click(view.getByRole('button', { name: /Intelligence Navigator/i }));
    expect(view.getByRole('dialog', { name: /Intelligence Navigator/i })).toBeInTheDocument();
  });

  it('routes to the persisted Actions queue from navigation', async () => {
    const user = userEvent.setup();
    const view = render(<MemoryRouter initialEntries={['/overview']}><App /></MemoryRouter>);
    await screen.findByText(/Operational overview/i);
    await user.click(view.getByRole('link', { name: /Actions/i }));
    expect(view.getByRole('heading', { name: 'Action queue' })).toBeInTheDocument();
  });

});
