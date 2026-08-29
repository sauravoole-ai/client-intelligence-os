import { StrictMode } from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { createClient } from './services/api';

const authenticatedSession = {
  user_id: 'user-1',
  display_name: 'Ada Lovelace',
  email: 'ada@example.com',
  workspace_id: 'workspace-1',
  workspace_name: 'Atlas Coaching',
  role: 'owner',
  csrf_token: 'csrf-for-this-session',
};

const clientResponse = {
  id: 'client-1', display_name: 'Client', external_reference: null, status: 'active',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

function renderApp(path = '/overview', strict = false) {
  const application = (
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>
  );
  return render(strict ? <StrictMode>{application}</StrictMode> : application);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('authenticated application bootstrap', () => {
  it('does not expose protected content while the session check is unresolved', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));

    renderApp('/clients/client-1');

    expect(screen.getByRole('status')).toHaveTextContent('Checking your secure session');
    expect(screen.queryByText('Operational overview')).not.toBeInTheDocument();
    expect(screen.queryByText('Client workspace')).not.toBeInTheDocument();
  });

  it('renders the operational application and server identity after auth/me succeeds', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(authenticatedSession)));

    renderApp();

    expect(await screen.findByText('Operational overview')).toBeInTheDocument();
    expect(screen.getByText('Atlas Coaching')).toBeInTheDocument();
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('renders a sign-in experience for an unauthenticated deep link', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })));

    renderApp('/analyses/analysis-1');

    const signIn = await screen.findByRole('link', { name: 'Sign in' });
    expect(signIn).toHaveAttribute('href', '/api/v1/auth/login');
    expect(screen.queryByText('Operational overview')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/email|password/i)).not.toBeInTheDocument();
  });

  it('shows an auth-service error instead of treating a failed session check as signed out', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })));

    renderApp();

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to verify your session');
    expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument();
  });

  it('keeps the newer authenticated session and CSRF token when an obsolete bootstrap returns 401', async () => {
    const bootstrapA = deferred<Response>();
    const bootstrapB = deferred<Response>();
    const sessionB = { ...authenticatedSession, display_name: 'Grace Hopper', csrf_token: 'csrf-session-b' };
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => bootstrapA.promise)
      .mockImplementationOnce(() => bootstrapB.promise)
      .mockResolvedValueOnce(jsonResponse(clientResponse, 201));
    vi.stubGlobal('fetch', fetchMock);

    renderApp('/overview', true);
    bootstrapB.resolve(jsonResponse(sessionB));
    expect(await screen.findByText('Grace Hopper')).toBeInTheDocument();

    await act(async () => {
      bootstrapA.resolve(new Response(null, { status: 401 }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('Operational overview')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument();
    await createClient({ display_name: 'Client' });
    expect(new Headers(fetchMock.mock.calls[2][1].headers).get('X-CSRF-Token')).toBe('csrf-session-b');
  });

  it('does not let an obsolete bootstrap success overwrite a newer unauthenticated state', async () => {
    const bootstrapA = deferred<Response>();
    const bootstrapB = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn()
      .mockImplementationOnce(() => bootstrapA.promise)
      .mockImplementationOnce(() => bootstrapB.promise));

    renderApp('/overview', true);
    bootstrapB.resolve(new Response(null, { status: 401 }));
    expect(await screen.findByRole('link', { name: 'Sign in' })).toBeInTheDocument();

    await act(async () => {
      bootstrapA.resolve(jsonResponse(authenticatedSession));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByText('Operational overview')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('posts logout, then clears the authenticated UI only after success', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(authenticatedSession))
      .mockResolvedValueOnce(jsonResponse({ status: 'logged_out' }))
      .mockResolvedValueOnce(jsonResponse(clientResponse, 201));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    renderApp();
    await user.click(await screen.findByRole('button', { name: 'Sign out' }));

    expect(await screen.findByRole('link', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.queryByText('Operational overview')).not.toBeInTheDocument();
    await createClient({ display_name: 'Client' });
    expect(new Headers(fetchMock.mock.calls[2][1].headers).has('X-CSRF-Token')).toBe(false);
  });

  it('keeps the authenticated UI and exposes a retryable error when logout fails', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(authenticatedSession))
      .mockResolvedValueOnce(new Response(null, { status: 503 }));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    renderApp();
    await user.click(await screen.findByRole('button', { name: 'Sign out' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to sign out');
    expect(screen.getByText('Operational overview')).toBeInTheDocument();
  });

  it('transitions to sign-in on a protected 401 but preserves the authenticated shell for 403', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(authenticatedSession))
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(jsonResponse(clientResponse, 201));
    vi.stubGlobal('fetch', fetchMock);

    renderApp('/clients');

    expect(await screen.findByRole('link', { name: 'Sign in' })).toBeInTheDocument();
    await createClient({ display_name: 'Client' });
    expect(new Headers(fetchMock.mock.calls[2][1].headers).has('X-CSRF-Token')).toBe(false);

    cleanup();
    fetchMock.mockReset()
      .mockResolvedValueOnce(jsonResponse(authenticatedSession))
      .mockResolvedValueOnce(new Response(null, { status: 403 }));
    renderApp('/clients');

    expect(await screen.findByRole('alert')).toHaveTextContent('Client directory unavailable');
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument();
  });

  it('replaces the previous CSRF token when a newer authenticated session boots', async () => {
    const sessionB = { ...authenticatedSession, display_name: 'Grace Hopper', csrf_token: 'csrf-session-b' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(authenticatedSession))
      .mockResolvedValueOnce(jsonResponse(sessionB))
      .mockResolvedValueOnce(jsonResponse(clientResponse, 201));
    vi.stubGlobal('fetch', fetchMock);

    renderApp();
    await screen.findByText('Ada Lovelace');
    cleanup();
    renderApp();
    await screen.findByText('Grace Hopper');

    await createClient({ display_name: 'Client' });
    expect(new Headers(fetchMock.mock.calls[2][1].headers).get('X-CSRF-Token')).toBe('csrf-session-b');
  });
});
