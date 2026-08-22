import { Link } from 'react-router-dom';
import { useRef, useState } from 'react';
import { ActionStatusConflictError, getAction, updateActionStatus } from '../services/api';
import type { ActionItem, ActionItemStatus } from '../types';

function formatDate(value: string | null) {
  if (!value) return null;
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

export default function ActionItemCard({ action, onChange, compact = false }: { action: ActionItem; onChange: (action: ActionItem) => void; compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ kind: 'error' | 'conflict'; message: string } | null>(null);
  const lock = useRef(false);

  const changeStatus = async (status: ActionItemStatus) => {
    if (lock.current || status === action.status) return;
    lock.current = true; setBusy(true); setFeedback(null);
    try { onChange(await updateActionStatus(action.id, { status, expected_version: action.version })); }
    catch (error) {
      setFeedback(error instanceof ActionStatusConflictError
        ? { kind: 'conflict', message: 'This Action Item was changed elsewhere.' }
        : { kind: 'error', message: error instanceof Error ? error.message : 'The Action Item could not be updated.' });
    } finally { lock.current = false; setBusy(false); }
  };

  const reload = async () => {
    if (lock.current) return;
    lock.current = true; setBusy(true);
    try { onChange(await getAction(action.id)); setFeedback(null); }
    catch { setFeedback({ kind: 'error', message: 'The latest Action Item could not be loaded.' }); }
    finally { lock.current = false; setBusy(false); }
  };

  return <article className={`action-item-card${compact ? ' action-item-card--compact' : ''}${action.status === 'completed' || action.status === 'dismissed' ? ' action-item-card--quiet' : ''}`} aria-busy={busy}>
    <div className="action-item-card__header"><div><div className="eyebrow">Operational Action Item · Priority {action.priority}</div><h3>{action.title}</h3></div><span className="badge">{action.status.replace('_', ' ')}</span></div>
    {!compact ? <p>{action.description}</p> : null}
    <dl className="action-item-card__meta"><div><dt>Created</dt><dd>{formatDate(action.created_at)}</dd></div><div><dt>Updated</dt><dd>{formatDate(action.updated_at)}</dd></div>{action.due_at ? <div><dt>Due</dt><dd>{formatDate(action.due_at)}</dd></div> : null}{action.completed_at ? <div><dt>Completed</dt><dd>{formatDate(action.completed_at)}</dd></div> : null}</dl>
    {!compact ? <div className="action-item-card__relations"><Link to={`/analyses/${action.analysis_id}`}>Source analysis</Link>{action.client_id ? <Link to={`/clients/${action.client_id}`}>Client workspace</Link> : <span>Anonymous analysis</span>}<span>Source: {action.source_action_id}</span></div> : null}
    <label className="field-stack" htmlFor={`action-status-${action.id}`}>Status<select id={`action-status-${action.id}`} value={action.status} disabled={busy} onChange={(event) => void changeStatus(event.target.value as ActionItemStatus)}><option value="open">Open</option><option value="in_progress">In progress</option><option value="completed">Completed</option><option value="dismissed">Dismissed</option></select></label>
    {feedback ? <div role="alert" className="form-feedback form-feedback--error"><p>{feedback.message}</p>{feedback.kind === 'conflict' ? <button className="secondary" type="button" disabled={busy} onClick={() => void reload()}>Reload action</button> : null}</div> : null}
  </article>;
}
