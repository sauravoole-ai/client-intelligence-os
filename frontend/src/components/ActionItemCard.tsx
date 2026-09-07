import { Link } from 'react-router-dom';
import { useEffect, useRef, useState } from 'react';
import { ActionStatusConflictError, getAction, listWorkspaceMembers, updateActionFollowUp, updateActionStatus } from '../services/api';
import type { ActionItem, ActionItemStatus, WorkspaceMember } from '../types';

function formatDate(value: string | null) {
  if (!value) return 'No due date';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function assigneeLabel(action: ActionItem) {
  if (!action.assignee) return 'Unassigned';
  const identity = action.assignee.display_name ?? action.assignee.email ?? 'Assigned member';
  return action.assignee.status === 'disabled' ? `${identity} (inactive)` : identity;
}

function localDateTime(value: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const part = (number: number) => String(number).padStart(2, '0');
  return `${date.getFullYear()}-${part(date.getMonth() + 1)}-${part(date.getDate())}T${part(date.getHours())}:${part(date.getMinutes())}`;
}

function awareDateTime(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime()) || localDateTime(date.toISOString()) !== value) throw new Error('Choose a valid local date and time.');
  return date.toISOString();
}

function memberLabel(member: WorkspaceMember) {
  return member.display_name ?? member.email ?? 'Workspace member';
}

interface ActionItemCardProps {
  action: ActionItem;
  onChange?: (action: ActionItem) => void;
  compact?: boolean;
  readOnly?: boolean;
  isOverdue?: boolean;
}

export default function ActionItemCard({ action, onChange, compact = false, readOnly = false, isOverdue = false }: ActionItemCardProps) {
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [assignee, setAssignee] = useState<string | null>(action.assignee_membership_id);
  const [dueAt, setDueAt] = useState(localDateTime(action.due_at));
  const [status, setStatus] = useState<ActionItemStatus>(action.status);
  const [outcome, setOutcome] = useState(action.completion_outcome ?? '');
  const [feedback, setFeedback] = useState<{ kind: 'error' | 'status'; message: string } | null>(null);
  const lock = useRef(false);
  const reset = () => { setAssignee(action.assignee_membership_id); setDueAt(localDateTime(action.due_at)); setStatus(action.status); setOutcome(action.completion_outcome ?? ''); };

  useEffect(() => {
    reset();
  }, [action.id, action.version]);

  const reloadAfterConflict = async () => {
    if (!onChange) return;
    try {
      const latest = await getAction(action.id);
      onChange(latest); setEditing(false); setAssignee(latest.assignee_membership_id); setDueAt(localDateTime(latest.due_at)); setStatus(latest.status); setOutcome(latest.completion_outcome ?? '');
    }
    catch { setFeedback({ kind: 'error', message: 'The latest Action Item could not be loaded.' }); }
  };

  const withMutation = async (request: () => Promise<ActionItem>) => {
    if (!onChange || lock.current) return;
    lock.current = true; setBusy(true); setFeedback(null);
    try { onChange(await request()); }
    catch (error) {
      if (error instanceof ActionStatusConflictError) {
        setFeedback({ kind: 'error', message: 'This Action Item was changed elsewhere. Review the latest state before trying again.' });
        await reloadAfterConflict();
      } else setFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'The Action Item could not be updated.' });
    } finally { lock.current = false; setBusy(false); }
  };

  const openEditor = async () => {
    reset(); setFeedback(null); setEditing(true);
    if (members.length) return;
    try { setMembers((await listWorkspaceMembers()).items); }
    catch (error) { setFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'Workspace members could not be loaded.' }); }
  };

  const saveFollowUp = async () => {
    let normalizedDue: string | null;
    try { normalizedDue = awareDateTime(dueAt); }
    catch (error) { setFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'Due date could not be validated.' }); return; }
    if (assignee === action.assignee_membership_id && normalizedDue === action.due_at) {
      setFeedback({ kind: 'status', message: 'No follow-up changes to save.' });
      return;
    }
    await withMutation(async () => {
      const updated = await updateActionFollowUp(action.id, { assignee_membership_id: assignee, due_at: normalizedDue, expected_version: action.version });
      setEditing(false); setFeedback({ kind: 'status', message: 'Follow-up saved.' });
      return updated;
    });
  };

  const saveStatus = async () => {
    const trimmedOutcome = outcome.trim();
    if (status === 'completed' && (!trimmedOutcome || trimmedOutcome.length > 2000)) {
      setFeedback({ kind: 'error', message: trimmedOutcome.length > 2000 ? 'Completion outcome must be 2000 characters or fewer.' : 'Enter a completion outcome before completing this Action Item.' });
      return;
    }
    await withMutation(async () => {
      const updated = await updateActionStatus(action.id, { status, expected_version: action.version, completion_outcome: status === 'completed' ? trimmedOutcome : null });
      setFeedback({ kind: 'status', message: status === 'completed' ? 'Action Item completed.' : 'Status saved.' });
      return updated;
    });
  };

  const historicalMember = action.assignee && action.assignee.status === 'disabled' && !members.some((member) => member.membership_id === action.assignee_membership_id);
  return <article className={`action-item-card${compact ? ' action-item-card--compact' : ''}${action.status === 'completed' || action.status === 'dismissed' ? ' action-item-card--quiet' : ''}${isOverdue ? ' action-item-card--overdue' : ''}`} aria-busy={busy}>
    <div className="action-item-card__header"><div><div className="eyebrow">Operational Action Item · Priority {action.priority}</div><h3>{action.title}</h3></div><div className="action-item-card__badges"><span className="badge">{action.status.replace('_', ' ')}</span>{isOverdue ? <span className="badge badge--danger">Overdue</span> : null}</div></div>
    {!compact ? <p>{action.description}</p> : null}
    <dl className="action-item-card__meta"><div><dt>Assignee</dt><dd>{assigneeLabel(action)}</dd></div><div><dt>Due</dt><dd>{formatDate(action.due_at)}</dd></div><div><dt>Updated</dt><dd>{formatDate(action.updated_at)}</dd></div>{action.completed_at ? <div><dt>Completed</dt><dd>{formatDate(action.completed_at)}</dd></div> : null}{action.completion_outcome ? <div><dt>Outcome</dt><dd>{action.completion_outcome}</dd></div> : null}</dl>
    {!compact ? <div className="action-item-card__relations"><Link to={`/analyses/${action.analysis_id}`}>Source analysis</Link>{action.client_id ? <Link to={`/clients/${action.client_id}`}>Client workspace</Link> : <span>Anonymous analysis</span>}<span>Source: {action.source_action_id}</span></div> : null}
    {!readOnly ? <div className="action-item-card__controls">
      <button className="secondary" type="button" disabled={busy} onClick={() => void openEditor()}>{editing ? 'Reset follow-up' : 'Edit follow-up'}</button>
      {editing ? <div className="action-item-card__editor">
        <label className="field-stack" htmlFor={`action-assignee-${action.id}`}>Assignee<select id={`action-assignee-${action.id}`} value={assignee ?? ''} disabled={busy} onChange={(event) => setAssignee(event.target.value || null)}><option value="">Unassigned</option>{historicalMember ? <option value={action.assignee_membership_id ?? ''} disabled>{assigneeLabel(action)}</option> : null}{members.map((member) => <option key={member.membership_id} value={member.membership_id}>{memberLabel(member)}</option>)}</select></label>
        <label className="field-stack" htmlFor={`action-due-${action.id}`}>Due date and time<input id={`action-due-${action.id}`} type="datetime-local" value={dueAt} disabled={busy} onChange={(event) => setDueAt(event.target.value)} /></label>
        <div className="action-item-card__actions"><button className="primary" type="button" disabled={busy} onClick={() => void saveFollowUp()}>{busy ? 'Saving…' : 'Save follow-up'}</button><button className="secondary" type="button" disabled={busy} onClick={() => { reset(); setEditing(false); }}>Cancel</button></div>
      </div> : null}
      <div className="action-item-card__status">
        <label className="field-stack" htmlFor={`action-status-${action.id}`}>Status<select id={`action-status-${action.id}`} value={status} disabled={busy} onChange={(event) => setStatus(event.target.value as ActionItemStatus)}><option value="open">Open</option><option value="in_progress">In progress</option><option value="completed">Completed</option><option value="dismissed">Dismissed</option></select></label>
        {status === 'completed' ? <label className="field-stack" htmlFor={`action-outcome-${action.id}`}>Completion outcome<textarea id={`action-outcome-${action.id}`} maxLength={2000} value={outcome} disabled={busy} aria-describedby={`action-outcome-help-${action.id}`} onChange={(event) => setOutcome(event.target.value)} /><span id={`action-outcome-help-${action.id}`} className="muted-text">Required to complete; 2000 characters maximum.</span></label> : null}
        <button className="secondary" type="button" disabled={busy || (status === action.status && (status !== 'completed' || outcome.trim() === (action.completion_outcome ?? '')))} onClick={() => void saveStatus()}>{status === 'completed' ? 'Complete Action' : 'Save status'}</button>
      </div>
      {feedback ? <div role={feedback.kind === 'error' ? 'alert' : 'status'} className={`form-feedback${feedback.kind === 'error' ? ' form-feedback--error' : ''}`}><p>{feedback.message}</p></div> : null}
    </div> : null}
  </article>;
}
