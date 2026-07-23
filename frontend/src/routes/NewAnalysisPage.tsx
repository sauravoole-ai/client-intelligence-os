import { FormEvent, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { createAnalysis } from '../services/api';
import type { AnalysisResponse } from '../types';

const emptyForm = {
  client_reference: '',
  analysis_period: '',
  conversation: '',
  engine_mode: 'deterministic' as 'auto' | 'llm' | 'deterministic',
};

function NewAnalysisPage() {
  const [form, setForm] = useState(emptyForm);
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState('');

  const charCount = useMemo(() => form.conversation.length, [form.conversation]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (status === 'loading') return;
    setStatus('loading');
    setErrorMessage('');
    try {
      const response = await createAnalysis({
        conversation: form.conversation,
        client_reference: form.client_reference || null,
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
            <span style={{ fontWeight: 600 }}>Anonymised client reference</span>
            <input disabled={isSubmitting} value={form.client_reference} onChange={(event) => setForm({ ...form, client_reference: event.target.value })} placeholder="ANON-004" />
          </label>
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
            <span style={{ fontWeight: 600 }}>Engine mode</span>
            <select disabled={isSubmitting} value={form.engine_mode} onChange={(event) => setForm({ ...form, engine_mode: event.target.value as 'auto' | 'llm' | 'deterministic' })}>
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
