import React from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { useEffect, useMemo, useRef, useState } from 'react';
import IntelligenceNavigator from './IntelligenceNavigator';
import type { AuthenticatedSession } from '../types';

const navItems = [
  { to: '/overview', label: 'Overview' },
  { to: '/clients', label: 'Clients' },
  { to: '/analyses', label: 'Analyses' },
  { to: '/actions', label: 'Actions' },
  { to: '/new-analysis', label: 'New Analysis' },
  { to: '/review-queue', label: 'Review Queue' },
  { to: '/audit', label: 'Audit' },
  { to: '/settings', label: 'Settings' },
];

function AppShell({
  children,
  session,
  onSignOut,
}: {
  children: React.ReactNode;
  session: AuthenticatedSession;
  onSignOut: () => Promise<void>;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [navigatorOpen, setNavigatorOpen] = useState(false);
  const [signOutBusy, setSignOutBusy] = useState(false);
  const [signOutError, setSignOutError] = useState('');
  const location = useLocation();
  const drawerRef = useRef<HTMLDivElement | null>(null);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (menuOpen) drawerRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
  }, [menuOpen]);

  const closeMenu = () => {
    setMenuOpen(false);
    menuButtonRef.current?.focus();
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMenuOpen(false);
        setNavigatorOpen(false);
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setNavigatorOpen(true);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const activeLabel = useMemo(() => {
    if (location.pathname.startsWith('/clients')) return 'Clients';
    if (location.pathname.startsWith('/analyses')) return 'Analyses';
    if (location.pathname.startsWith('/actions')) return 'Actions';
    const active = navItems.find((item) => item.to === location.pathname);
    return active?.label ?? 'Workspace';
  }, [location.pathname]);

  const accountName = session.display_name || session.email || 'Signed-in user';

  const handleSignOut = async () => {
    if (signOutBusy) return;
    setSignOutBusy(true);
    setSignOutError('');
    try {
      await onSignOut();
    } catch (error) {
      setSignOutError(error instanceof Error ? error.message : 'Unable to sign out. Please retry.');
      setSignOutBusy(false);
    }
  };

  return (
    <div className="app-shell">
      <div className="app-shell__layout">
        <aside className="app-shell__nav" aria-label="Primary navigation">
          <div className="nav-brand">
            <div className="nav-brand__mark">CI</div>
            <div>
              <div>Client Intelligence OS</div>
              <small>Operational evidence workspace</small>
            </div>
          </div>

          <div className="shell-status">
            <div className="status-pill">Trusted review layer</div>
            <div className="status-pill status-pill--muted">Deterministic baseline active</div>
          </div>

          <nav className="stack nav-stack" aria-label="Primary">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
              >
                <span>{item.label}</span>
                <span aria-hidden="true">↗</span>
              </NavLink>
            ))}
          </nav>

          <div className="card card--tight shell-card">
            <div className="eyebrow">Workspace</div>
            <div className="shell-card__title">{session.workspace_name || 'Current workspace'}</div>
            <div className="shell-card__meta">{accountName} • {session.role}</div>
          </div>
        </aside>

        <main className="app-shell__main">
          <header className="panel shell-header">
            <div>
              <div className="eyebrow">Intelligence workspace</div>
              <h1>{activeLabel}</h1>
            </div>
            <div className="toolbar" role="toolbar" aria-label="Workspace tools">
              <button className="secondary" onClick={() => setNavigatorOpen(true)}>Intelligence Navigator</button>
              <div className="shell-account" aria-label="Current account">
                <span>{accountName}</span>
                <button className="secondary" type="button" disabled={signOutBusy} onClick={() => void handleSignOut()}>{signOutBusy ? 'Signing out…' : 'Sign out'}</button>
              </div>
              <button ref={menuButtonRef} className="secondary mobile-menu-button" aria-label="Open navigation drawer" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
                Menu
              </button>
            </div>
            {signOutError ? <p className="shell-sign-out-error" role="alert">{signOutError}</p> : null}
          </header>

          {children}
        </main>
      </div>

      {menuOpen && (
        <div className="drawer-backdrop" onClick={closeMenu}>
          <div ref={drawerRef} role="dialog" aria-modal="true" aria-label="Mobile navigation" className="drawer" onClick={(event) => event.stopPropagation()}>
            <div className="drawer__header">
              <strong>Navigation</strong>
              <button className="secondary" onClick={closeMenu}>Close</button>
            </div>
            {navItems.map((item) => (
              <Link key={item.to} to={item.to} className="nav-link" onClick={() => setMenuOpen(false)}>
                <span>{item.label}</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {navigatorOpen && <IntelligenceNavigator onClose={() => setNavigatorOpen(false)} />}
    </div>
  );
}

export default AppShell;
