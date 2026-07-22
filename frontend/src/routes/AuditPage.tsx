import { auditHistory } from '../data/mockData';

function AuditPage() {
  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h2 className="page__title">Audit history</h2>
          <p className="page__subtitle">A clear record of review actions and state changes, backed by isolated mock data.</p>
        </div>
        <button className="secondary">Timeline view</button>
      </div>

      <div className="panel panel--soft" style={{ padding: 16 }}>
        <div className="grid">
          {auditHistory.map((entry) => (
            <div key={entry.id} className="card audit-card">
              <div className="audit-card__head">
                <strong>{entry.action} • {entry.entity}</strong>
                <span className="badge">{entry.timestamp}</span>
              </div>
              <div className="muted-text">{entry.reason}</div>
              <div className="audit-card__footer">
                <span className="badge">Actor: {entry.actor}</span>
                <span className="badge">Engine: {entry.engine}</span>
                <span className="badge">Prompt: {entry.promptVersion}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default AuditPage;
