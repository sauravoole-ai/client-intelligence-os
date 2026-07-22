import React from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { useEffect, useMemo, useRef, useState } from 'react';
import IntelligenceNavigator from './IntelligenceNavigator';

const navItems = [
  { to: '/overview', label: 'Overview' },
  { to: '/clients', label: 'Clients' },
  { to: '/new-analysis', label: 'New Analysis' },
  { to: '/review-queue', label: 'Review Queue' },
  { to: '/audit', label: 'Audit' },
  { to: '/settings', label: 'Settings' },
];

function AppShell({ children }: { children: React.ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [navigatorOpen, setNavigatorOpen] = useState(false);
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
    const active = navItems.find((item) => item.to === location.pathname);
    return active?.label ?? 'Workspace';
  }, [location.pathname]);

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
            <div className="shell-card__title">Northstar Coaching Group</div>
            <div className="shell-card__meta">Global review queue • 6 pending • 3 high-attention cases</div>
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
              <button ref={menuButtonRef} className="secondary mobile-menu-button" aria-label="Open navigation drawer" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
                Menu
              </button>
            </div>
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
