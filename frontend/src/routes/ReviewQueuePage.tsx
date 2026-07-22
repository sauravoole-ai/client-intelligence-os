import { useMemo, useState } from 'react';
import { reviewQueue } from '../data/mockData';

function ReviewQueuePage() {
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'edited' | 'rejected'>('all');

  const filtered = useMemo(() => {
    return reviewQueue.filter((item) => statusFilter === 'all' || item.status === statusFilter);
  }, [statusFilter]);

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h2 className="page__title">Review queue</h2>
          <p className="page__subtitle">A structured operational review surface for pending findings and follow-ups.</p>
        </div>
        <button className="secondary">Bulk action</button>
      </div>

      <div className="chip-row">
        {(['all', 'pending', 'edited', 'rejected'] as const).map((value) => (
          <button key={value} className={statusFilter === value ? 'chip chip--active' : 'chip'} onClick={() => setStatusFilter(value)}>
            {value === 'all' ? 'All' : value}
          </button>
        ))}
      </div>

      <div className="panel panel--soft" style={{ padding: 16 }}>
        {filtered.length === 0 ? (
          <div className="empty-state">
            <h3>No review items</h3>
            <p>Your selection is currently empty.</p>
          </div>
        ) : (
          <div className="grid">
            {filtered.map((item) => (
              <div key={item.id} className="card queue-card">
                <div>
                  <div className="queue-card__title">
                    <strong>{item.title}</strong>
                    <span className="badge">{item.category}</span>
                  </div>
                  <div className="muted-text">{item.coach} • {item.updatedAt}</div>
                </div>
                <div className="queue-card__meta">
                  <span className="badge badge--warning">{item.severity}</span>
                  <span className="badge">{item.evidenceCount} evidence</span>
                  <span className="badge">{item.status}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default ReviewQueuePage;
