import { overviewMetrics, activityFeed } from '../data/mockData';

function OverviewPage() {
  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h2 className="page__title">Operational overview</h2>
          <p className="page__subtitle">Evidence-led review signals for the current coaching workspace.</p>
        </div>
        <div className="toolbar">
          <label className="field-label">
            <span className="sr-only">Date range</span>
            <select defaultValue="last-7-days">
              <option value="last-7-days">Last 7 days</option>
              <option value="last-14-days">Last 14 days</option>
              <option value="last-30-days">Last 30 days</option>
            </select>
          </label>
          <button className="primary">Export view</button>
        </div>
      </div>

      <div className="panel panel--soft" style={{ padding: 16 }}>
        <div className="grid grid--3">
          <div className="card">
            <div className="eyebrow">High attention clients</div>
            <div className="metric-value">{overviewMetrics.attentionCount}</div>
            <div className="badge badge--warning">Estimated • demonstration data</div>
          </div>
          <div className="card">
            <div className="eyebrow">Pending reviews</div>
            <div className="metric-value">{overviewMetrics.pendingReviews}</div>
            <div className="badge">Review queue active</div>
          </div>
          <div className="card">
            <div className="eyebrow">Estimated review time saved</div>
            <div className="metric-value">{overviewMetrics.reviewTimeSaved}</div>
            <div className="badge badge--positive">Sample operational metric</div>
          </div>
        </div>
      </div>

      <div className="grid grid--2">
        <div className="card stack">
          <div className="page__header">
            <h3>Operating status summary</h3>
            <span className="badge">Stable</span>
          </div>
          <div className="stack">
            <div className="list-row">
              <span>Follow-ups due</span>
              <strong>{overviewMetrics.followUpsDue}</strong>
            </div>
            <div className="list-row">
              <span>Completion rate</span>
              <strong>{overviewMetrics.completionRate}</strong>
            </div>
            <div className="list-row">
              <span>Coach workload</span>
              <strong>{overviewMetrics.workload}</strong>
            </div>
          </div>
        </div>
        <div className="card stack">
          <div className="page__header">
            <h3>Recent activity</h3>
            <span className="badge">Internal mock data</span>
          </div>
          <ul className="bullet-list">
            {activityFeed.map((entry) => (
              <li key={entry}>{entry}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="grid grid--2">
        <div className="card stack">
          <div className="page__header">
            <h3>High-attention clients</h3>
            <span className="badge badge--danger">4 requiring review</span>
          </div>
          <div className="stack">
            {['ANON-001', 'ANON-005', 'ANON-008', 'ANON-011'].map((value) => (
              <div key={value} className="card card--tight list-row">
                <div>
                  <strong>{value}</strong>
                  <div className="muted-text">Fatigue and stress attention signal</div>
                </div>
                <span className="badge">Open</span>
              </div>
            ))}
          </div>
        </div>
        <div className="card stack">
          <div className="page__header">
            <h3>Deterministic fallback analyses</h3>
            <span className="badge badge--warning">3 active</span>
          </div>
          <div className="muted-text">These are clearly marked as deterministic baseline outputs and are not presented as live LLM-generated review content.</div>
        </div>
      </div>
    </div>
  );
}

export default OverviewPage;
