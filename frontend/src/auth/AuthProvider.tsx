import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { AuthenticatedSession } from '../types';
import {
  AuthenticationRequiredError,
  clearApiAuthentication,
  configureApiAuthentication,
  getAuthenticatedSession,
  logout,
} from '../services/api';

type AuthState =
  | { status: 'loading' }
  | { status: 'authenticated'; session: AuthenticatedSession }
  | { status: 'unauthenticated' }
  | { status: 'error'; message: string };

type AuthContextValue = {
  state: AuthState;
  retry: () => void;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const authEpoch = useRef(0);

  const invalidate = useCallback(() => {
    authEpoch.current += 1;
    clearApiAuthentication();
    setState({ status: 'unauthenticated' });
  }, []);

  useEffect(() => {
    const epoch = authEpoch.current + 1;
    authEpoch.current = epoch;
    const isCurrent = () => authEpoch.current === epoch;
    clearApiAuthentication();
    setState({ status: 'loading' });

    void getAuthenticatedSession().then((session) => {
      if (!isCurrent()) return;
      configureApiAuthentication({ csrfToken: session.csrf_token, onUnauthorized: invalidate });
      setState({ status: 'authenticated', session });
    }).catch((error: unknown) => {
      if (!isCurrent()) return;
      clearApiAuthentication();
      if (error instanceof AuthenticationRequiredError) {
        setState({ status: 'unauthenticated' });
        return;
      }
      setState({
        status: 'error',
        message: error instanceof Error ? error.message : 'Unable to verify your session. Please retry.',
      });
    });

    return () => {
      if (isCurrent()) {
        authEpoch.current += 1;
        clearApiAuthentication();
      }
    };
  }, [attempt, invalidate]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const signOut = useCallback(async () => {
    await logout();
    invalidate();
  }, [invalidate]);
  const value = useMemo(() => ({ state, retry, signOut }), [retry, signOut, state]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider.');
  return context;
}
