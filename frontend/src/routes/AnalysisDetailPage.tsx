import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getAnalysis } from '../services/api';
import type {
  AnalysisResponse,
  CoachAction,
  EvidenceReference,
  Finding,
  RiskFlag,
} from '../types';

const NOT_FOUND_MESSAGE = 'The requested analysis was not found.';
const GENERIC_ERROR_MESSAGE = 'This saved analysis is temporarily unavailable. Please try again.';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function readableLabel(value: string) {
  return value.replace(/_/g, ' ');
}

function confidenceLabel(value: number) {
  return `${Math.round(value * 100)}% confidence`;
}

function formatCreatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Date unavailable';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function EvidenceList({ evidence }: { evidence: EvidenceReference[] }) {
  if (evidence.length === 0) {
    return <p className="analysis-detail__empty-subsection">No supporting evidence was stored.</p>;
  }

  return (
    <div className="evidence-list" aria-label="Supporting evidence">
      {evidence.map((item) => (
        <figure className="evidence-card" key={item.message_id}>
          <blockquote>“{item.quote}”</blockquote>
          <figcaption>
            <span>{item.day} · {item.speaker}</span>
            <span>Message {item.message_id}</span>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

function StatusRow({
  classification,
  confidence,
  reviewStatus,
}: {
  classification: string;
  confidence?: number;
  reviewStatus: string;
}) {
  return (
    <div className="analysis-detail__status-row">
      <span className="badge">Classification: {readableLabel(classification)}</span>
      {confidence !== undefined && <span className="badge">{confidenceLabel(confidence)}</span>}
      <span className="badge">Review status: {readableLabel(reviewStatus)}</span>
    </div>
  );
}

function FindingCard({ finding, summary = false }: { finding: Finding; summary?: boolean }) {
  return (
    <article className={summary ? 'detail-card detail-card--summary' : 'detail-card'}>
      <div className="detail-card__header">
        <div>
          <div className="eyebrow">{summary ? 'Weekly summary' : readableLabel(finding.category)}</div>
          <h3>{finding.title}</h3>
        </div>
        {!summary && <span className="badge">Category: {readableLabel(finding.category)}</span>}
      </div>
      <p className="detail-card__statement">{finding.statement}</p>
      <StatusRow
        classification={finding.classification}
        confidence={finding.confidence}
        reviewStatus={finding.review_status}
      />
      <EvidenceList evidence={finding.evidence} />
    </article>
  );
}

function RiskFlagCard({ risk }: { risk: RiskFlag }) {
  return (
    <article className="detail-card detail-card--risk">
      <div className="detail-card__header">
        <div>
          <div className="eyebrow">Risk flag</div>
          <h3>{risk.title}</h3>
        </div>
        <span className="badge badge--danger">Severity: {readableLabel(risk.severity)}</span>
      </div>
      <p className="detail-card__statement">{risk.rationale}</p>
      <StatusRow
        classification={risk.classification}
        confidence={risk.confidence}
        reviewStatus={risk.review_status}
      />
      <EvidenceList evidence={risk.evidence} />
    </article>
  );
}

function RecommendedActionCard({ action }: { action: CoachAction }) {
  return (
    <article className="detail-card detail-card--action">
      <div className="detail-card__header">
        <div>
          <div className="eyebrow">Recommended action</div>
          <h3>{action.action}</h3>
        </div>
        <span className="badge badge--positive">Priority {action.priority}</span>
      </div>
      <p className="detail-card__statement">{action.rationale}</p>
      <StatusRow classification={action.classification} reviewStatus={action.review_status} />
      <div className="linked-findings">
        <strong>Linked findings</strong>
        {action.linked_finding_ids.length > 0 ? (
          <div className="chip-row">
            {action.linked_finding_ids.map((findingId) => (
              <span className="chip" key={findingId}>{findingId}</span>
            ))}
          </div>
        ) : (
          <span className="analysis-detail__empty-subsection">No linked findings were stored.</span>
        )}
      </div>
      <EvidenceList evidence={action.evidence} />
    </article>
  );
}

function AnalysisMetadata({ analysis }: { analysis: AnalysisResponse }) {
  return (
    <section className="analysis-metadata panel" aria-label="Analysis metadata">
      <div className="analysis-metadata__primary">
        <div>
          <div className="eyebrow">Saved analysis</div>
          <h2>{analysis.client_reference || 'Anonymous'}</h2>
          <p>{analysis.analysis_period}</p>
        </div>
        <div className="analysis-detail__status-row">
          {analysis.fallback_reason && (
            <span className="badge badge--warning">Fallback used: {analysis.fallback_reason}</span>
          )}
          <span className="badge">
            {analysis.validation_warnings.length} validation warning{analysis.validation_warnings.length === 1 ? '' : 's'}
          </span>
        </div>
      </div>
      <dl className="analysis-metadata__grid">
        <div><dt>Created</dt><dd><time dateTime={analysis.created_at}>{formatCreatedAt(analysis.created_at)}</time></dd></div>
        <div><dt>Engine</dt><dd>{analysis.engine}</dd></div>
        <div><dt>Prompt version</dt><dd>{analysis.prompt_version}</dd></div>
        <div><dt>Analysis ID</dt><dd className="analysis-id">{analysis.analysis_id}</dd></div>
      </dl>
    </section>
  );
}

function AnalysisDetailSkeleton() {
  return (
    <div className="analysis-detail-skeleton" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">Loading saved analysis</span>
      <div className="analysis-skeleton analysis-detail-skeleton__hero" aria-hidden="true">
        <div className="analysis-skeleton__line analysis-skeleton__line--short" />
        <div className="analysis-skeleton__line analysis-skeleton__line--title" />
        <div className="analysis-skeleton__grid">
          <div className="analysis-skeleton__block" />
          <div className="analysis-skeleton__block" />
          <div className="analysis-skeleton__block" />
        </div>
      </div>
      {[0, 1].map((item) => (
        <div className="analysis-skeleton" aria-hidden="true" key={item}>
          <div className="analysis-skeleton__line analysis-skeleton__line--title" />
          <div className="analysis-skeleton__line" />
          <div className="analysis-skeleton__line" />
        </div>
      ))}
    </div>
  );
}

function AnalysisDetailErrorState({
  kind,
  onRetry,
}: {
  kind: 'not-found' | 'error' | 'invalid';
  onRetry: () => void;
}) {
  const isNotFound = kind === 'not-found';
  const title = isNotFound
    ? 'Analysis not found'
    : kind === 'invalid'
      ? 'Invalid analysis link'
      : 'Analysis could not be loaded';
  const message = isNotFound
    ? 'The requested saved analysis does not exist or is no longer available.'
    : kind === 'invalid'
      ? 'This link does not contain a valid analysis ID.'
      : GENERIC_ERROR_MESSAGE;

  return (
    <section className="analysis-state card" role="alert" aria-labelledby="analysis-detail-error-title">
      <div className="badge badge--danger">Retrieval issue</div>
      <h2 id="analysis-detail-error-title">{title}</h2>
      <p>{message}</p>
      <div className="toolbar">
        {kind === 'error' && <button className="secondary" type="button" onClick={onRetry}>Retry</button>}
        <Link className="primary inline-link" to="/analyses">Back to analyses</Link>
      </div>
    </section>
  );
}

function AnalysisSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="analysis-detail__section">
      <div className="analysis-detail__section-heading">
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {children}
    </section>
  );
}

function AnalysisDetailPage() {
  const { analysisId } = useParams();
  const [status, setStatus] = useState<'loading' | 'success' | 'not-found' | 'error' | 'invalid'>('loading');
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    if (!analysisId || !UUID_PATTERN.test(analysisId)) {
      setStatus('invalid');
      setAnalysis(null);
      return;
    }

    let active = true;
    setStatus('loading');
    getAnalysis(analysisId)
      .then((response) => {
        if (!active) return;
        setAnalysis(response);
        setStatus('success');
      })
      .catch((error: unknown) => {
        if (!active) return;
        setAnalysis(null);
        setStatus(error instanceof Error && error.message === NOT_FOUND_MESSAGE ? 'not-found' : 'error');
      });

    return () => {
      active = false;
    };
  }, [analysisId, requestVersion]);

  const retry = () => setRequestVersion((version) => version + 1);

  if (status === 'loading') return <AnalysisDetailSkeleton />;
  if (status === 'not-found' || status === 'error' || status === 'invalid') {
    return <AnalysisDetailErrorState kind={status} onRetry={retry} />;
  }
  if (!analysis) return <AnalysisDetailErrorState kind="error" onRetry={retry} />;

  return (
    <div className="page analysis-detail-page">
      <nav aria-label="Analysis navigation">
        <Link className="analysis-back-link" to="/analyses">← Back to analyses</Link>
      </nav>

      <AnalysisMetadata analysis={analysis} />

      <AnalysisSection title="Weekly summary" description="The stored synthesis for this analysis period.">
        <FindingCard finding={analysis.weekly_summary} summary />
      </AnalysisSection>

      <AnalysisSection title="Findings" description="Structured observations grounded in the saved analysis output.">
        {analysis.findings.length > 0 ? (
          <div className="analysis-detail__cards">
            {analysis.findings.map((finding) => <FindingCard finding={finding} key={finding.finding_id} />)}
          </div>
        ) : <p className="analysis-detail__empty-subsection card">No findings were stored.</p>}
      </AnalysisSection>

      <AnalysisSection title="Risk flags" description="Attention signals requiring informed human review.">
        {analysis.risk_flags.length > 0 ? (
          <div className="analysis-detail__cards">
            {analysis.risk_flags.map((risk) => <RiskFlagCard risk={risk} key={risk.risk_id} />)}
          </div>
        ) : <p className="analysis-detail__empty-subsection card">No risk flags were stored.</p>}
      </AnalysisSection>

      <AnalysisSection title="Recommended actions" description="Prioritised next steps from the saved analysis.">
        {analysis.recommended_actions.length > 0 ? (
          <div className="analysis-detail__cards">
            {analysis.recommended_actions.map((action) => <RecommendedActionCard action={action} key={action.action_id} />)}
          </div>
        ) : <p className="analysis-detail__empty-subsection card">No recommended actions were stored.</p>}
      </AnalysisSection>

      <div className="analysis-detail__split">
        <AnalysisSection title="Missing information" description="Information unavailable in the stored evidence set.">
          {analysis.missing_information.length > 0 ? (
            <ul className="card bullet-list">
              {analysis.missing_information.map((item) => <li key={item}>{item}</li>)}
            </ul>
          ) : <p className="analysis-detail__empty-subsection card">No missing information was recorded.</p>}
        </AnalysisSection>

        <AnalysisSection title="Validation warnings" description="Cautions retained with the analysis output.">
          {analysis.validation_warnings.length > 0 ? (
            <ul className="card bullet-list">
              {analysis.validation_warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          ) : <p className="analysis-detail__empty-subsection card">No validation warnings were recorded.</p>}
        </AnalysisSection>
      </div>
    </div>
  );
}

export default AnalysisDetailPage;
