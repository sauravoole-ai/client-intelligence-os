import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { clients } from '../data/mockData';

type ReviewState = 'pending' | 'approved' | 'edited' | 'rejected';

type Category = {
  key: string;
  title: string;
  statement: string;
  classification: string;
  evidenceIds: string[];
};

const categories: Category[] = [
  { key: 'nutrition_adherence', title: 'Nutrition adherence', statement: 'Meal planning remains inconsistent and requires coach attention.', classification: 'AI-generated inference', evidenceIds: ['msg-003'] },
  { key: 'exercise_steps', title: 'Exercise and steps', statement: 'Movement is present but not yet reliably structured.', classification: 'Client-reported information', evidenceIds: ['msg-002'] },
  { key: 'sleep', title: 'Sleep', statement: 'Short sleep and fatigue episodes are recurring.', classification: 'Client-reported information', evidenceIds: ['msg-001', 'msg-004'] },
  { key: 'water_intake', title: 'Water intake', statement: 'Tracking remains incomplete for daily hydration.', classification: 'Missing information', evidenceIds: [] },
];

function ClientWorkspacePage() {
  const { clientId } = useParams();
  const client = clients.find((entry) => entry.id === clientId);
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null);
  const [reviewState, setReviewState] = useState<Record<string, ReviewState>>({});
  const [activeReview, setActiveReview] = useState<{ key: string; action: 'edited' | 'rejected' } | null>(null);
  const [reviewNote, setReviewNote] = useState('');
  const [statusMessage, setStatusMessage] = useState('Review actions update locally and preserve context for future API persistence.');

  const evidence = useMemo(() => {
    return [
      { id: 'msg-001', day: 'Day 1', speaker: 'Client', quote: 'I slept only around 5 hours last night.' },
      { id: 'msg-002', day: 'Day 1', speaker: 'Client', quote: 'Did some walking inside the house.' },
      { id: 'msg-003', day: 'Day 2', speaker: 'Client', quote: 'I did not get time to plan meals.' },
      { id: 'msg-004', day: 'Day 3', speaker: 'Coach', quote: 'We need to look at your sleep and stress more carefully.' },
    ];
  }, []);

  const handleReviewAction = (key: string, state: ReviewState) => {
    setReviewState((current) => ({ ...current, [key]: state }));
    setStatusMessage(`Updated ${key} to ${state}.`);
  };

  const submitReviewNote = () => {
    if (!activeReview || !reviewNote.trim()) return;
    handleReviewAction(activeReview.key, activeReview.action);
    setActiveReview(null);
    setReviewNote('');
  };

  const selectedCategory = categories.find((category) => category.key === selectedEvidence);
  const highlightedIds = selectedCategory?.evidenceIds ?? (selectedEvidence ? [selectedEvidence] : []);

  if (!client) {
    return <div className="card">Client not found.</div>;
  }

  return (
    <div className="page">
      <div className="panel" style={{ padding: 20 }}>
        <div className="page__header">
          <div>
            <div className="eyebrow">Client intelligence workspace</div>
            <h2 className="page__title">{client.reference}</h2>
            <p className="page__subtitle">Week 12 • {client.attention} attention • Coach {client.coach}</p>
          </div>
          <div className="toolbar">
            <span className="badge">Analysis engine: deterministic</span>
            <span className="badge badge--warning">Fallback active</span>
          </div>
        </div>

        <div className="card" style={{ marginTop: 16 }}>
          <div className="page__header">
            <div>
              <h3 style={{ margin: 0 }}>Weekly summary</h3>
              <p className="muted-text" style={{ margin: '6px 0 0' }}>The client reported continued movement and engagement, while nutrition planning and daily measurement remain incomplete. This review is evidence-led and operationally framed.</p>
            </div>
            <div className="toolbar">
              <button className="primary" onClick={() => handleReviewAction('summary', 'approved')}>Approve</button>
              <button className="secondary" onClick={() => setActiveReview({ key: 'summary', action: 'edited' })}>Edit</button>
              <button className="secondary" onClick={() => setActiveReview({ key: 'summary', action: 'rejected' })}>Reject</button>
            </div>
          </div>
          <div className="muted-text" style={{ marginTop: 10 }}>{statusMessage}</div>
        </div>

        <div className="grid grid--2" style={{ marginTop: 16 }}>
          <div className="card stack">
            <h3 style={{ margin: 0 }}>Intelligence categories</h3>
            {categories.map((category) => (
              <div key={category.key} className="card card--tight" style={{ display: 'grid', gap: 8 }}>
                <div className="list-row">
                  <strong>{category.title}</strong>
                  <span className="badge">{category.classification}</span>
                </div>
                <div>{category.statement}</div>
                <div className="toolbar">
                  <button className="secondary" onClick={() => setSelectedEvidence(category.key)}>View evidence</button>
                  <button className="secondary" onClick={() => handleReviewAction(category.key, 'approved')}>Approve</button>
                  <button className="secondary" onClick={() => setActiveReview({ key: category.key, action: 'edited' })}>Edit</button>
                  <button className="secondary" onClick={() => setActiveReview({ key: category.key, action: 'rejected' })}>Reject</button>
                </div>
                <div className="muted-text">Status: {reviewState[category.key] ?? 'pending'}</div>
              </div>
            ))}
          </div>
          <div className="card stack">
            <h3 style={{ margin: 0 }}>Evidence trace</h3>
            {evidence.map((item) => (
              <button key={item.id} className={highlightedIds.includes(item.id) ? 'secondary evidence-message evidence-message--active' : 'secondary evidence-message'} onClick={() => setSelectedEvidence(item.id)} aria-pressed={highlightedIds.includes(item.id)}>
                <strong>{item.id}</strong>
                <div className="muted-text">{item.day} • {item.speaker}</div>
                <div style={{ marginTop: 6 }}>{item.quote}</div>
              </button>
            ))}
            <div className="card card--tight">
              <strong>Operational guidance</strong>
              <p className="muted-text" style={{ margin: '6px 0 0' }}>Evidence is presented as a reviewable provenance layer and does not replace human review.</p>
            </div>
          </div>
        </div>
      </div>
      {activeReview && (
        <div className="review-sheet" role="dialog" aria-modal="true" aria-labelledby="review-note-title">
          <div className="review-sheet__panel stack">
            <div>
              <div className="eyebrow">Human review decision</div>
              <h3 id="review-note-title">{activeReview.action === 'rejected' ? 'Reject finding' : 'Edit finding'}</h3>
            </div>
            <label className="field-stack">
              <span>{activeReview.action === 'rejected' ? 'Rejection reason (required)' : 'Edit rationale (required)'}</span>
              <textarea autoFocus required value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} rows={4} />
            </label>
            <div className="toolbar review-sheet__actions">
              <button className="secondary" onClick={() => { setActiveReview(null); setReviewNote(''); }}>Cancel</button>
              <button className="primary" disabled={!reviewNote.trim()} onClick={submitReviewNote}>Confirm {activeReview.action === 'rejected' ? 'rejection' : 'edit'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ClientWorkspacePage;
