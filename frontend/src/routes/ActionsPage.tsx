import { useEffect, useState } from 'react';
import ActionItemCard from '../components/ActionItemCard';
import { listActions } from '../services/api';
import type { ActionItem, ActionItemStatus } from '../types';

export default function ActionsPage() {
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [filter, setFilter] = useState<'all' | ActionItemStatus>('all');
  const [state, setState] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true; setState('loading');
    listActions({ ...(filter === 'all' ? {} : { status: filter }), limit: 100 }).then((response) => { if (active) { setActions(response.items); setState('success'); } }).catch((error: unknown) => { if (active) { setMessage(error instanceof Error ? error.message : 'The Action queue could not be loaded.'); setState('error'); } });
    return () => { active = false; };
  }, [filter, retry]);
  const replace = (updated: ActionItem) => setActions((current) => current.map((item) => item.id === updated.id ? updated : item));
  return <div className="page actions-page"><div className="page__header"><div><div className="eyebrow">Operations</div><h2 className="page__title">Action queue</h2><p className="page__subtitle">Persisted work explicitly created from approved recommendations.</p></div><label className="field-stack" htmlFor="action-filter">Status<select id="action-filter" value={filter} onChange={(event) => setFilter(event.target.value as 'all' | ActionItemStatus)}><option value="all">All</option><option value="open">Open</option><option value="in_progress">In progress</option><option value="completed">Completed</option><option value="dismissed">Dismissed</option></select></label></div>
    {state === 'loading' ? <div className="panel analysis-state" role="status" aria-busy="true"><h3>Loading Action Items…</h3></div> : state === 'error' ? <div className="panel analysis-state stack" role="alert"><h3>Action queue unavailable</h3><p>{message}</p><button className="secondary" type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button></div> : actions.length === 0 ? <div className="panel analysis-state stack"><h3>No Action Items</h3><p>No persisted work matches this status.</p></div> : <div className="action-queue">{actions.map((action) => <ActionItemCard key={action.id} action={action} onChange={replace} />)}</div>}
  </div>;
}
