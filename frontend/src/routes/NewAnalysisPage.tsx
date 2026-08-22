import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { createAnalysis, listClients } from '../services/api';
import type { AnalysisResponse, Client } from '../types';

const emptyForm = {
  client_id: '',
  analysis_period: '',
  conversation: '',
  engine_mode: 'deterministic' as 'auto' | 'llm' | 'deterministic',
};

function NewAnalysisPage() {
  const [form, setForm] = useState(emptyForm);
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [clients, setClients] = useState<Client[]>([]);
  const [clientLoadState, setClientLoadState] = useState<'loading' | 'success' | 'error'>('loading');

  useEffect(() => {
    let active = true;
    listClients({ limit: 100 }).then((response) => {
      if (!active) return;
      setClients(response.items.filter((client) => client.status === 'active'));
      setClientLoadState('success');
    }).catch(() => {
      if (active) setClientLoadState('error');
    });
    return () => { active = false; };
  }, []);

  const charCount = useMemo(() => form.conversation.length, [form.conversation]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (status === 'loading') return;
    setStatus('loading');
    setErrorMessage('');
    try {
      const response = await createAnalysis({
        conversation: form.conversation,
        ...(form.client_id ? { client_id: form.client_id } : {}),
        analysis_period: form.analysis_period || null,
        engine_mode: form.engine_mode,
      });
      setResult(response);
      setStatus('success');
    } catch (error) {
      setStatus('error');
      setErrorMessage(error instanceof Error ? error.message : 'Unable to create analysis.');
    }
  };

  const canSubmit = form.conversation.trim().length >= 20 && status !== 'loading';
  const isSubmitting = status === 'loading';

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h2 className="page__title">New analysis</h2>
          <p className="page__subtitle">Submit a client conversation for evidence-grounded review. The current environment uses the deterministic backend by default.</p>
        </div>
      </div>

      <div className="grid grid--2">
        <form className="card stack" onSubmit={handleSubmit}>
          <label className="stack">
            <span style={{ fontWeight: 600 }}>Linked client</span>
            <select aria-describedby="client-selector-help" disabled={isSubmitting || clientLoadState === 'loading'} value={form.client_id} onChange={(event) => setForm({ ...form, client_id: event.target.value })}>
              <option value="">No linked client</option>
              {clients.map((client) => <option key={client.id} value={client.id}>{client.display_name}{client.external_reference ? ` — ${client.external_reference}` : ''}</option>)}
            </select>
          </label>
          <div id="client-selector-help" className="form-hint">
            {clientLoadState === 'loading' ? 'Loading active clients…' : clientLoadState === 'error' ? <span role="status">Clients could not be loaded. Anonymous analysis remains available.</span> : clients.length === 0 ? 'No active clients yet. Anonymous analysis remains available.' : 'The backend resolves the selected client reference.'}
            {' '}<Link to="/clients">Manage clients</Link>
          </div>
          <label className="stack">
            <span style={{ fontWeight: 600 }}>Analysis period</span>
            <input disabled={isSubmitting} value={form.analysis_period} onChange={(event) => setForm({ ...form, analysis_period: event.target.value })} placeholder="Week 13" />
          </label>
          <label className="stack">
            <span style={{ fontWeight: 600 }}>Conversation text</span>
            <textarea disabled={isSubmitting} required minLength={20} value={form.conversation} onChange={(event) => setForm({ ...form, conversation: event.target.value })} rows={10} placeholder="Day 1
Client: ...
Coach: ..." />
          </label>
          <div className="stack">
            <label htmlFor="analysis-engine-mode" style={{ fontWeight: 600 }}>Engine mode</label>
            <select id="analysis-engine-mode" disabled={isSubmitting} value={form.engine_mode} onChange={(event) => setForm({ ...form, engine_mode: event.target.value as 'auto' | 'llm' | 'deterministic' })}>
              <option value="auto">Auto (uses deterministic fallback when needed)</option>
              <option value="deterministic">Deterministic</option>
              <option value="llm">LLM</option>
            </select>
            <div className="form-hint">Deterministic is the safe local default and never calls an LLM.</div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <div style={{ color: 'var(--ink-muted)', fontSize: '0.92rem' }}>{charCount} characters</div>
            <button className="primary" type="submit" disabled={!canSubmit}>{status === 'loading' ? 'Submitting…' : 'Submit analysis'}</button>
          </div>
        </form>

        <div className="card stack" aria-live="polite" aria-busy={status === 'loading'}>
          <h3 style={{ margin: 0 }}>Submission status</h3>
          {status === 'success' && result ? (
            <div className="stack">
              <div className="badge badge--positive">Completed</div>
              <div><strong>Client:</strong> {result.client_reference || 'Anonymous'}</div>
              <div><strong>Engine:</strong> {result.engine}</div>
              <div><strong>Fallback:</strong> {result.fallback_reason || 'None'}</div>
              <div><strong>Findings:</strong> {result.findings.length}</div>
              <div className="toolbar">
                <Link className="primary inline-link" to={`/analyses/${result.analysis_id}`}>Open saved analysis</Link>
                <Link className="chip inline-link" to="/analyses">View all analyses</Link>
              </div>
            </div>
          ) : status === 'error' ? (
            <div className="stack">
              <div className="badge badge--danger">Submission issue</div>
              <div>{errorMessage}</div>
              <button className="secondary" type="button" onClick={() => setStatus('idle')}>Try again</button>
            </div>
          ) : status === 'loading' ? (
            <div className="loading-state"><span className="signal-pulse" aria-hidden="true" />Analysing evidence…</div>
          ) : (
            <div style={{ color: 'var(--ink-muted)' }}>No submission yet. The form will clearly surface validation, engine-unavailable and network states.</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default NewAnalysisPage;
