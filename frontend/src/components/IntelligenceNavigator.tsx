import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';

type Command = {
  id: string;
  label: string;
  description: string;
  route: string;
  keywords: string[];
};

const commands: Command[] = [
  {
    id: 'overview',
    label: 'Open overview',
    description: 'Review operational health and workload.',
    route: '/overview',
    keywords: ['overview', 'dashboard', 'health'],
  },
  {
    id: 'new-analysis',
    label: 'Start a new analysis',
    description: 'Open the analysis submission workflow.',
    route: '/new-analysis',
    keywords: ['new analysis', 'start analysis', 'analysis'],
  },
  {
    id: 'review-queue',
    label: 'Open pending reviews',
    description: 'Review outstanding evidence and follow-ups.',
    route: '/review-queue',
    keywords: ['pending reviews', 'reviews', 'queue'],
  },
  {
    id: 'audit',
    label: 'Go to audit history',
    description: 'Inspect review changes and decisions.',
    route: '/audit',
    keywords: ['audit', 'history', 'changes'],
  },
  {
    id: 'client',
    label: 'Find client ANON-001',
    description: 'Open the client intelligence workspace.',
    route: '/clients/anon-001',
    keywords: ['anon-001', 'client', 'workspace'],
  },
];

function IntelligenceNavigator({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return commands.slice(0, 5);
    return commands.filter((command) =>
      [command.label, command.description, ...command.keywords].some((value) => value.toLowerCase().includes(normalized)),
    );
  }, [query]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (!filtered.length) return;
      setSelectedIndex((current) => (current + 1) % filtered.length);
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (!filtered.length) return;
      setSelectedIndex((current) => (current - 1 + filtered.length) % filtered.length);
    }
    if (event.key === 'Enter' && filtered[selectedIndex]) {
      event.preventDefault();
      handleSelect(filtered[selectedIndex].route);
    }
  };

  const handleSelect = (route: string) => {
    navigate(route);
    onClose();
  };

  return (
    <div role="dialog" aria-modal="true" aria-label="Intelligence Navigator" className="navigator-backdrop" onClick={onClose}>
      <div className="navigator" onClick={(event) => event.stopPropagation()}>
        <div className="navigator__header">
          <div>
            <div className="eyebrow">Local navigation assistance</div>
            <h2>Intelligence Navigator</h2>
          </div>
          <button className="secondary" onClick={onClose}>Close</button>
        </div>

        <label className="field-stack">
          <span>Ask for a route or action</span>
          <input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={handleKeyDown} placeholder="Show high-attention clients" aria-label="Navigator search" />
        </label>

        <div className="navigator__list">
          {filtered.length === 0 ? (
            <div className="card empty-state">No local commands matched that request.</div>
          ) : (
            filtered.map((command, index) => (
              <button key={command.id} className={selectedIndex === index ? 'secondary navigator__item navigator__item--active' : 'secondary navigator__item'} onClick={() => handleSelect(command.route)}>
                <strong>{command.label}</strong>
                <div className="muted-text">{command.description}</div>
              </button>
            ))
          )}
        </div>

        <div className="muted-text">This navigator is local and rule-based. It will later connect to a live AI assistant without making any paid API calls.</div>
      </div>
    </div>
  );
}

export default IntelligenceNavigator;
