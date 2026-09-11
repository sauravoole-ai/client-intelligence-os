import { useEffect, useState } from 'react';
import {
  getLongitudinalSignal,
  LongitudinalSignalConflictError,
  reviewLongitudinalSignal,
} from '../services/api';
import type { LongitudinalEvidenceReference, LongitudinalSignal, SignalReviewRequest } from '../types';

type Props = { signal: LongitudinalSignal; onSignalUpdated?: (signal: LongitudinalSignal) => void };

function evidenceLabel(evidence: LongitudinalEvidenceReference) {
  if (evidence.analysis_id) return `Analysis ${evidence.artifact_kind?.replace('_', ' ') ?? 'artifact'}: ${evidence.artifact_id}`;
  return `Action Item field: ${evidence.action_field}`;
}

export function IntelligenceReviewPanel({ signal, onSignalUpdated }: Props) {
  const [current, setCurrent] = useState(signal);
  const [editing, setEditing] = useState(false);
  const [summary, setSummary] = useState(signal.summary);
  const [explanation, setExplanation] = useState(signal.explanation);
  const [reason, setReason] = useState('');
  const [feedback, setFeedback] = useState<string | null>(null);
  const [conflicted, setConflicted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setCurrent(signal);
    setEditing(false);
    setSummary(signal.summary);
    setExplanation(signal.explanation);
    setReason('');
    setFeedback(null);
    setConflicted(false);
  }, [signal.id, signal.version]);

  const apply = async (request: SignalReviewRequest) => {
    setSubmitting(true); setFeedback(null); setConflicted(false);
    try {
      const updated = await reviewLongitudinalSignal(current.id, request);
      setCurrent(updated); onSignalUpdated?.(updated);
      setFeedback('Review decision saved.'); setEditing(false);
    } catch (error) {
      if (error instanceof LongitudinalSignalConflictError) {
        setConflicted(true); setFeedback('This signal changed elsewhere. Reload it before making another decision.');
      } else setFeedback('The review could not be saved. Please try again.');
    } finally { setSubmitting(false); }
  };

  const reload = async () => {
    setSubmitting(true); setFeedback(null);
    try {
      const updated = await getLongitudinalSignal(current.id);
      setCurrent(updated); onSignalUpdated?.(updated);
      setSummary(updated.summary); setExplanation(updated.explanation); setReason(''); setEditing(false); setConflicted(false);
    } catch { setFeedback('The latest signal could not be loaded. Please try again.'); }
    finally { setSubmitting(false); }
  };

  const decision = (action: SignalReviewRequest['action']) => {
    const normalizedReason = reason.trim();
    if ((action === 'reject' || action === 'edit_and_approve') && !normalizedReason) {
      setFeedback('A reason is required for this review decision.'); return;
    }
    void apply({
      action, expected_version: current.version, reason: action === 'approve' || action === 'revalidate' ? null : normalizedReason,
      ...(action === 'edit_and_approve' ? { summary: summary.trim(), explanation: explanation.trim() } : {}),
    });
  };

  const needsRevalidation = current.trust_state === 'needs_revalidation';
  return <section className={`intelligence-review ${needsRevalidation ? 'intelligence-review--revalidation' : ''}`} aria-label="Intelligence review">
    <header className="intelligence-review__header">
      <div><p className="eyebrow">Longitudinal intelligence</p><h2>{current.summary}</h2></div>
      <span className={`badge ${needsRevalidation ? 'badge--warning' : 'badge--danger'}`}>{current.trust_state.replace('_', ' ')}</span>
    </header>
    <p>{needsRevalidation ? 'Needs revalidation before it can be trusted again.' : 'Draft — human review required before this signal is trusted.'}</p>
    <p>{current.explanation}</p>
    <div><h3>Evidence locators</h3><ul className="intelligence-review__evidence">
      {current.evidence.map((evidence, index) => <li key={`${evidence.analysis_id ?? evidence.action_item_id}-${index}`}>
        <span>{evidenceLabel(evidence)}</span><span className="badge">{evidence.evidence_role}</span>
      </li>)}
    </ul></div>
    {editing && <div className="intelligence-review__editor">
      <label className="field-stack">Edited summary<input aria-label="Edited summary" value={summary} onChange={(event) => setSummary(event.target.value)} /></label>
      <label className="field-stack">Edited explanation<textarea aria-label="Edited explanation" value={explanation} onChange={(event) => setExplanation(event.target.value)} /></label>
    </div>}
    {(editing || current.trust_state === 'draft') && <label className="field-stack">Review reason{editing ? ' (required)' : ' (required to reject)'}<textarea aria-label="Review reason" value={reason} onChange={(event) => setReason(event.target.value)} /></label>}
    {feedback && <p className="form-feedback form-feedback--error" role="alert">{feedback}</p>}
    <div className="intelligence-review__actions">
      {conflicted ? <button className="secondary" type="button" onClick={() => void reload()} disabled={submitting}>Reload signal</button> : <>
        {needsRevalidation ? <button className="primary" type="button" onClick={() => decision('revalidate')} disabled={submitting}>Revalidate signal</button> : <>
          <button className="primary" type="button" onClick={() => decision('approve')} disabled={submitting}>Approve signal</button>
          {!editing && <button className="secondary" type="button" onClick={() => setEditing(true)}>Edit and approve signal</button>}
          {editing && <button className="primary" type="button" onClick={() => decision('edit_and_approve')} disabled={submitting}>Save edited approval</button>}
          <button className="secondary" type="button" onClick={() => decision('reject')} disabled={submitting}>Reject signal</button>
        </>}
      </>}
    </div>
  </section>;
}
