import type { ReactNode } from 'react';
import { useAuth } from './AuthProvider';

function AuthLoading() {
  return (
    <main className="auth-screen" aria-busy="true">
      <section className="auth-panel" role="status" aria-live="polite">
        <div className="signal-pulse" aria-hidden="true" />
        <div>
          <div className="eyebrow">Client Intelligence OS</div>
          <h1>Checking your secure session</h1>
          <p>Preparing your workspace without exposing operational data.</p>
        </div>
      </section>
    </main>
  );
}

function SignIn() {
  return (
    <main className="auth-screen">
      <section className="auth-panel auth-panel--entry" aria-labelledby="sign-in-title">
        <div className="nav-brand__mark" aria-hidden="true">CI</div>
        <div className="eyebrow">Client Intelligence OS</div>
        <h1 id="sign-in-title">AI-powered client intelligence with human-controlled actions</h1>
        <p>Sign in to access your secure operational workspace.</p>
        <a className="primary auth-panel__action" href="/api/v1/auth/login">Sign in</a>
      </section>
    </main>
  );
}

function AuthError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <main className="auth-screen">
      <section className="auth-panel auth-panel--entry" role="alert" aria-live="assertive">
        <div className="eyebrow">Session check unavailable</div>
        <h1>Unable to verify your session</h1>
        <p>{message}</p>
        <button className="secondary auth-panel__action" type="button" onClick={onRetry}>Retry</button>
      </section>
    </main>
  );
}

export function AuthGate({ children }: { children: (session: Extract<ReturnType<typeof useAuth>['state'], { status: 'authenticated' }>['session']) => ReactNode }) {
  const { state, retry } = useAuth();
  if (state.status === 'loading') return <AuthLoading />;
  if (state.status === 'unauthenticated') return <SignIn />;
  if (state.status === 'error') return <AuthError message={state.message} onRetry={retry} />;
  return <>{children(state.session)}</>;
}
