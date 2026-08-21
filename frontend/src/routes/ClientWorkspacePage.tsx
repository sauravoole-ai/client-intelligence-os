import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import ActionItemCard from '../components/ActionItemCard';
import { getClient, listClientActions, listClientAnalyses } from '../services/api';
import type { ActionItem, Client, PersistedAnalysisResponse } from '../types';

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function ClientWorkspacePage() {
  const { clientId = '' } = useParams();
  const [client, setClient] = useState<Client | null>(null);
  const [analyses, setAnalyses] = useState<PersistedAnalysisResponse[]>([]);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [state, setState] = useState<'loading' | 'success' | 'not-found' | 'error'>('loading');
  const [message, setMessage] = useState('');
  const [retryKey, setRetryKey] = useState(0);
  useEffect(() => {
    let active = true;
    setState('loading');
    Promise.all([getClient(clientId), listClientAnalyses(clientId, { limit: 100 }), listClientActions(clientId)]).then(([clientResponse, analysisResponse, actionResponse]) => {
      if (!active) return;
      setClient(clientResponse); setAnalyses(analysisResponse.items); setActions(actionResponse.items); setState('success');
    }).catch((error: unknown) => {
      if (!active) return;
      const text = error instanceof Error ? error.message : 'The client workspace could not be loaded.';
      setMessage(text); setState(text.includes('not found') ? 'not-found' : 'error');
    });
    return () => { active = false; };
  }, [clientId, retryKey]);
  if (state === 'loading') return <div className="panel analysis-state stack" role="status" aria-busy="true"><h3>Loading client workspace…</h3><p>Retrieving client details and saved analyses.</p></div>;
  if (state === 'not-found') return <div className="panel analysis-state stack" role="alert"><h3>Client not found</h3><p>The requested client record does not exist.</p><Link to="/clients">Return to clients</Link></div>;
  if (state === 'error' || !client) return <div className="panel analysis-state stack" role="alert"><h3>Workspace unavailable</h3><p>{message}</p><button className="secondary" type="button" onClick={() => setRetryKey((value) => value + 1)}>Retry</button></div>;
  return <div className="page client-workspace">
    <Link className="analysis-back-link" to="/clients">← Client directory</Link>
    <section className="panel client-workspace__header"><div><div className="eyebrow">Client workspace</div><h2 className="page__title">{client.display_name}</h2><p className="page__subtitle">{client.external_reference ?? 'No external reference'}</p></div><span className="badge">{client.status}</span><dl className="client-workspace__metadata"><div><dt>Created</dt><dd>{formatDate(client.created_at)}</dd></div><div><dt>Updated</dt><dd>{formatDate(client.updated_at)}</dd></div></dl></section>
    <section className="stack" aria-labelledby="analysis-history-title"><div><div className="eyebrow">Persisted intelligence</div><h2 id="analysis-history-title">Analysis history</h2></div>
      {analyses.length === 0 ? <div className="card empty-state"><h3>No linked analyses</h3><p>This client has no persisted analysis history yet.</p><Link to="/new-analysis">Create an analysis</Link></div> : analyses.map((analysis) => <article className="analysis-list-item" key={analysis.analysis_id}><div className="analysis-list-item__heading"><div><div className="eyebrow">{formatDate(analysis.created_at)}</div><h3>{analysis.analysis_period}</h3></div><span className="badge">{analysis.review_status.replace('_', ' ')}</span></div><dl className="client-analysis-meta"><div><dt>Engine</dt><dd>{analysis.engine}</dd></div><div><dt>Warnings</dt><dd>{analysis.validation_warnings.length}</dd></div><div><dt>Review version</dt><dd>{analysis.review_version}</dd></div></dl>{analysis.review_note ? <p className="muted-text"><strong>Review note:</strong> {analysis.review_note}</p> : null}<div className="analysis-list-item__footer"><Link className="primary inline-link" to={`/analyses/${analysis.analysis_id}`}>Open saved analysis</Link></div></article>)}
    </section>
    <section className="stack" aria-labelledby="client-actions-title"><div><div className="eyebrow">Operational workflow</div><h2 id="client-actions-title">Action Items</h2></div>{actions.length === 0 ? <div className="card empty-state"><h3>No Action Items</h3><p>This client has no persisted operational work yet.</p></div> : <div className="action-queue">{actions.map((action) => <ActionItemCard key={action.id} compact action={action} onChange={(updated) => setActions((current) => current.map((item) => item.id === updated.id ? updated : item))} />)}</div>}</section>
  </div>;
}

export default ClientWorkspacePage;
