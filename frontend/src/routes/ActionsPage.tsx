import { useEffect, useState } from 'react';
import ActionItemCard from '../components/ActionItemCard';
import { listActions } from '../services/api';
import type { ActionItem, ActionQueue } from '../types';

const queueOptions: Array<{ value: ActionQueue | null; label: string }> = [
  { value: null, label: 'All Action Items' },
  { value: 'open', label: 'Open' },
  { value: 'due_today', label: 'Due today' },
  { value: 'overdue', label: 'Overdue' },
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'completed', label: 'Completed' },
  { value: 'no_due_date', label: 'No due date' },
];

function emptyMessage(queue: ActionQueue | null) {
  if (queue === 'no_due_date') return 'No Action Items without a due date.';
  if (queue === 'due_today') return 'No Action Items due today.';
  if (queue === 'overdue') return 'No overdue Action Items.';
  if (queue === 'upcoming') return 'No upcoming Action Items.';
  if (queue === 'completed') return 'No completed Action Items.';
  if (queue === 'open') return 'No open Action Items.';
  return 'No Action Items are available.';
}

export default function ActionsPage() {
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [queue, setQueue] = useState<ActionQueue | null>(null);
  const [state, setState] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    setActions([]);
    setState('loading');
    listActions({ ...(queue ? { queue } : {}), limit: 100 }).then((response) => {
      if (!active) return;
      setActions(response.items);
      setState('success');
    }).catch((error: unknown) => {
      if (!active) return;
      setMessage(error instanceof Error ? error.message : 'The Action queue could not be loaded.');
      setState('error');
    });
    return () => { active = false; };
  }, [queue, retry]);

  return <div className="page actions-page">
    <div className="page__header">
      <div><div className="eyebrow">Operations</div><h2 className="page__title">Action queue</h2><p className="page__subtitle">Persisted work explicitly created from approved recommendations.</p></div>
    </div>
    <div className="action-queue-controls" aria-label="Action queue views">
      {queueOptions.map((option) => <button key={option.label} type="button" className={`chip${queue === option.value ? ' chip--active' : ''}`} aria-pressed={queue === option.value} onClick={() => setQueue(option.value)}>{option.label}</button>)}
    </div>
    {state === 'loading' ? <div className="panel analysis-state" role="status" aria-busy="true"><h3>Loading Action Items…</h3></div>
      : state === 'error' ? <div className="panel analysis-state stack" role="alert"><h3>Action queue unavailable</h3><p>{message}</p><button className="secondary" type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button></div>
        : actions.length === 0 ? <div className="panel analysis-state stack"><h3>No Action Items</h3><p>{emptyMessage(queue)}</p></div>
          : <div className="action-queue">{actions.map((action) => <ActionItemCard key={action.id} action={action} isOverdue={queue === 'overdue'} onChange={() => setRetry((value) => value + 1)} />)}</div>}
  </div>;
}
