import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listAnalyses } from '../services/api';
import type { AnalysisListResponse, AnalysisResponse } from '../types';

const PAGE_OFFSET = 0;
const PAGE_LIMIT = 20;
const RETRIEVAL_ERROR_MESSAGE = 'Saved analyses are temporarily unavailable. Please try again.';

function formatCreatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Date unavailable';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function AnalysisListItem({ analysis }: { analysis: AnalysisResponse }) {
  return (
    <article className="analysis-list-item">
      <div className="analysis-list-item__heading">
        <div>
          <div className="eyebrow">Saved analysis</div>
          <h3>{analysis.client_reference || 'Anonymous'}</h3>
          <p>{analysis.analysis_period}</p>
        </div>
        <div className="analysis-list-item__statuses" aria-label="Analysis status">
          {analysis.fallback_reason && (
            <span className="badge badge--warning">Fallback used: {analysis.fallback_reason}</span>
          )}
          {analysis.validation_warnings.length > 0 && (
            <span className="badge">
              {analysis.validation_warnings.length} validation warning{analysis.validation_warnings.length === 1 ? '' : 's'}
            </span>
          )}
        </div>
      </div>

      <dl className="analysis-list-item__metadata">
        <div>
          <dt>Created</dt>
          <dd><time dateTime={analysis.created_at}>{formatCreatedAt(analysis.created_at)}</time></dd>
        </div>
        <div>
          <dt>Engine</dt>
          <dd>{analysis.engine}</dd>
        </div>
        <div>
          <dt>Findings</dt>
          <dd>{analysis.findings.length}</dd>
        </div>
        <div>
          <dt>Risk flags</dt>
          <dd>{analysis.risk_flags.length}</dd>
        </div>
        <div>
          <dt>Actions</dt>
          <dd>{analysis.recommended_actions.length}</dd>
        </div>
      </dl>

      <div className="analysis-list-item__footer">
        <Link
          className="primary inline-link"
          to={`/analyses/${analysis.analysis_id}`}
          aria-label={`Open analysis for ${analysis.client_reference || 'Anonymous'}`}
        >
          Open analysis
        </Link>
      </div>
    </article>
  );
}

function AnalysisListSkeleton() {
  return (
    <div className="analysis-list" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">Loading saved analyses</span>
      {[0, 1, 2].map((item) => (
        <div className="analysis-skeleton" aria-hidden="true" key={item}>
          <div className="analysis-skeleton__line analysis-skeleton__line--short" />
          <div className="analysis-skeleton__line analysis-skeleton__line--title" />
          <div className="analysis-skeleton__grid">
            <div className="analysis-skeleton__block" />
            <div className="analysis-skeleton__block" />
            <div className="analysis-skeleton__block" />
          </div>
        </div>
      ))}
    </div>
  );
}

function AnalysisEmptyState() {
  return (
    <section className="analysis-state card" aria-labelledby="empty-analyses-title">
      <div className="eyebrow">Saved workspace</div>
      <h3 id="empty-analyses-title">No saved analyses yet</h3>
      <p>Completed analyses will appear here after they have been successfully persisted.</p>
      <Link className="primary inline-link" to="/new-analysis">Create an analysis</Link>
    </section>
  );
}

function AnalysisErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="analysis-state card" role="alert" aria-labelledby="analysis-error-title">
      <div className="badge badge--danger">Retrieval issue</div>
      <h3 id="analysis-error-title">Saved analyses could not be loaded</h3>
      <p>{RETRIEVAL_ERROR_MESSAGE}</p>
      <button className="secondary" type="button" onClick={onRetry}>Retry</button>
    </section>
  );
}

function AnalysesPage() {
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [result, setResult] = useState<AnalysisListResponse | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    let active = true;
    setStatus('loading');

    listAnalyses({ offset: PAGE_OFFSET, limit: PAGE_LIMIT })
      .then((response) => {
        if (!active) return;
        setResult(response);
        setStatus('success');
      })
      .catch(() => {
        if (!active) return;
        setResult(null);
        setStatus('error');
      });

    return () => {
      active = false;
    };
  }, [requestVersion]);

  const retry = () => setRequestVersion((version) => version + 1);

  return (
    <div className="page analyses-page">
      <div className="page__header analyses-page__header">
        <div>
          <div className="eyebrow">Persisted intelligence</div>
          <h2 className="page__title">Saved analyses</h2>
          <p className="page__subtitle">Review completed analysis records without exposing source conversations.</p>
        </div>
        {status === 'success' && result && (
          <div className="analyses-page__count" aria-live="polite">
            <strong>{result.returned_count}</strong>
            <span>returned</span>
          </div>
        )}
      </div>

      {status === 'loading' && <AnalysisListSkeleton />}
      {status === 'error' && <AnalysisErrorState onRetry={retry} />}
      {status === 'success' && result?.items.length === 0 && <AnalysisEmptyState />}
      {status === 'success' && result && result.items.length > 0 && (
        <section className="analysis-list" aria-label="Saved analyses">
          {result.items.map((analysis) => (
            <AnalysisListItem analysis={analysis} key={analysis.analysis_id} />
          ))}
        </section>
      )}
    </div>
  );
}

export default AnalysesPage;
