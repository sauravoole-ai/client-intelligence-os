import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { clients } from '../data/mockData';

function ClientsPage() {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'High' | 'Elevated' | 'Steady'>('all');

  const filtered = useMemo(() => {
    return clients.filter((client) => {
      const matchesQuery = `${client.reference} ${client.nextAction}`.toLowerCase().includes(query.toLowerCase());
      const matchesFilter = filter === 'all' || client.attention === filter;
      return matchesQuery && matchesFilter;
    });
  }, [query, filter]);

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h2 className="page__title">Client directory</h2>
          <p className="page__subtitle">Search, filter and prioritise review-ready client work.</p>
        </div>
        <div className="toolbar">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search client reference" aria-label="Search client directory" />
          <select value={filter} onChange={(event) => setFilter(event.target.value as 'all' | 'High' | 'Elevated' | 'Steady')} aria-label="Filter by attention level">
            <option value="all">All attention levels</option>
            <option value="High">High</option>
            <option value="Elevated">Elevated</option>
            <option value="Steady">Steady</option>
          </select>
        </div>
      </div>

      <div className="chip-row" aria-label="Attention filters">
        {(['all', 'High', 'Elevated', 'Steady'] as const).map((value) => (
          <button key={value} className={filter === value ? 'chip chip--active' : 'chip'} onClick={() => setFilter(value)}>
            {value === 'all' ? 'All' : value}
          </button>
        ))}
      </div>

      <div className="panel panel--soft" style={{ padding: 16 }}>
        {filtered.length === 0 ? (
          <div className="empty-state">
            <h3>No matching clients</h3>
            <p>Try broadening the search and filter criteria.</p>
          </div>
        ) : (
          <div className="grid">
            {filtered.map((client) => (
              <div key={client.id} className="card client-card">
                <div className="client-card__main">
                  <div className="client-card__identity">
                    <strong>{client.reference}</strong>
                    <span className="badge">{client.attention} attention</span>
                  </div>
                  <div className="muted-text">Next action • {client.nextAction}</div>
                </div>
                <div className="client-card__meta">
                  <span className="badge">{client.reviews} pending reviews</span>
                  <span className="badge badge--positive">Coach {client.coach}</span>
                  <Link className="primary inline-link" to={`/clients/${client.id}`}>Open workspace</Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default ClientsPage;
