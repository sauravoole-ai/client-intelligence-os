import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ClientConflictError, createClient, listClients } from '../services/api';
import type { Client, ClientStatus } from '../types';

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value));
}

function ClientsPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [loadState, setLoadState] = useState<'loading' | 'success' | 'error'>('loading');
  const [loadError, setLoadError] = useState('');
  const [retryKey, setRetryKey] = useState(0);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<'all' | ClientStatus>('all');
  const [showCreate, setShowCreate] = useState(false);
  const [displayName, setDisplayName] = useState('');
  const [externalReference, setExternalReference] = useState('');
  const [createState, setCreateState] = useState<'idle' | 'loading' | 'error' | 'success'>('idle');
  const [createMessage, setCreateMessage] = useState('');

  useEffect(() => {
    let active = true;
    setLoadState('loading');
    listClients({ limit: 100 }).then((response) => {
      if (!active) return;
      setClients(response.items);
      setLoadState('success');
    }).catch((error: unknown) => {
      if (!active) return;
      setLoadError(error instanceof Error ? error.message : 'The client directory could not be loaded.');
      setLoadState('error');
    });
    return () => { active = false; };
  }, [retryKey]);

  const filtered = useMemo(() => {
    const search = query.trim().toLowerCase();
    return clients.filter((client) => {
      const matchesQuery = !search || `${client.display_name} ${client.external_reference ?? ''}`.toLowerCase().includes(search);
      return matchesQuery && (filter === 'all' || client.status === filter);
    });
  }, [clients, filter, query]);

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (createState === 'loading' || !displayName.trim()) return;
    setCreateState('loading');
    setCreateMessage('');
    try {
      const created = await createClient({ display_name: displayName.trim(), external_reference: externalReference.trim() || null });
      setClients((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setDisplayName('');
      setExternalReference('');
      setCreateMessage(`${created.display_name} was added to the directory.`);
      setCreateState('success');
      setShowCreate(false);
    } catch (error) {
      setCreateMessage(error instanceof ClientConflictError ? error.message : error instanceof Error ? error.message : 'The client could not be created.');
      setCreateState('error');
    }
  };

  return <div className="page clients-page">
    <div className="page__header"><div><div className="eyebrow">Client operations</div><h2 className="page__title">Client directory</h2><p className="page__subtitle">Durable client records and their saved intelligence history.</p></div><button className="primary" type="button" disabled={createState === 'loading'} onClick={() => setShowCreate((value) => !value)}>{showCreate ? 'Close form' : 'New client'}</button></div>
    {showCreate ? <form className="card client-create-form" onSubmit={handleCreate} aria-busy={createState === 'loading'}>
      <div><h3>Add a client</h3><p className="muted-text">Create the durable record before linking new analyses.</p></div>
      <label className="field-stack" htmlFor="client-display-name">Display name</label><input id="client-display-name" required maxLength={255} disabled={createState === 'loading'} value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
      <label className="field-stack" htmlFor="client-external-reference">External reference <span className="muted-text">Optional</span></label><input id="client-external-reference" maxLength={255} disabled={createState === 'loading'} value={externalReference} onChange={(event) => setExternalReference(event.target.value)} />
      <button className="primary" type="submit" disabled={!displayName.trim() || createState === 'loading'}>{createState === 'loading' ? 'Creating…' : 'Create client'}</button>
    </form> : null}
    {createMessage ? <p role={createState === 'error' ? 'alert' : 'status'} aria-live="polite" className={createState === 'error' ? 'form-feedback form-feedback--error' : 'form-feedback'}>{createMessage}</p> : null}
    <div className="toolbar client-directory-tools"><label className="sr-only" htmlFor="client-search">Search client directory</label><input id="client-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name or reference" /><label className="sr-only" htmlFor="client-status-filter">Filter by status</label><select id="client-status-filter" value={filter} onChange={(event) => setFilter(event.target.value as 'all' | ClientStatus)}><option value="all">All statuses</option><option value="active">Active</option><option value="archived">Archived</option></select></div>
    {loadState === 'loading' ? <div className="panel analysis-state stack" role="status" aria-busy="true"><div className="analysis-skeleton__line analysis-skeleton__line--title" /><p>Loading the client directory…</p></div>
      : loadState === 'error' ? <div className="panel analysis-state stack" role="alert"><h3>Client directory unavailable</h3><p>{loadError}</p><button className="secondary" type="button" onClick={() => setRetryKey((value) => value + 1)}>Retry</button></div>
        : clients.length === 0 ? <div className="panel analysis-state stack"><h3>No clients yet</h3><p>Create the first client record, or continue running anonymous analyses.</p></div>
          : filtered.length === 0 ? <div className="panel analysis-state stack"><h3>No matching clients</h3><p>Try a broader search or another status.</p></div>
            : <div className="client-directory-list">{filtered.map((client) => <article key={client.id} className="card client-directory-item"><div><div className="eyebrow">{client.external_reference ?? 'No external reference'}</div><h3>{client.display_name}</h3></div><dl className="client-directory-item__meta"><div><dt>Status</dt><dd>{client.status}</dd></div><div><dt>Created</dt><dd>{formatDate(client.created_at)}</dd></div><div><dt>Updated</dt><dd>{formatDate(client.updated_at)}</dd></div></dl><Link className="primary inline-link" to={`/clients/${client.id}`}>Open workspace</Link></article>)}</div>}
  </div>;
}

export default ClientsPage;
