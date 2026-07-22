import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('application shell', () => {
  it('renders the overview page by default', () => {
    const view = render(
      <MemoryRouter initialEntries={['/overview']}>
        <App />
      </MemoryRouter>,
    );

    expect(view.getByText(/Operational overview/i)).toBeInTheDocument();
  });

  it('opens the intelligence navigator from the shell', async () => {
    const user = userEvent.setup();
    const view = render(
      <MemoryRouter initialEntries={['/overview']}>
        <App />
      </MemoryRouter>,
    );

    await user.click(view.getByRole('button', { name: /Intelligence Navigator/i }));
    expect(view.getByRole('dialog', { name: /Intelligence Navigator/i })).toBeInTheDocument();
  });

  it('requires a reason before a finding can be rejected', async () => {
    const user = userEvent.setup();
    const view = render(
      <MemoryRouter initialEntries={['/clients/anon-001']}>
        <App />
      </MemoryRouter>,
    );

    await user.click(view.getAllByRole('button', { name: 'Reject' })[1]);
    const confirm = view.getByRole('button', { name: /Confirm rejection/i });
    expect(confirm).toBeDisabled();
    await user.type(view.getByLabelText(/Rejection reason/i), 'Source message does not support this finding.');
    expect(confirm).toBeEnabled();
  });
});
