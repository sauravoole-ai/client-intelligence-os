import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  AnalysisReviewConflictError,
  ActionMaterializationConflictError,
  getAnalysis,
  listAnalysisActions,
  materializeAnalysisActions,
  updateAnalysisReview,
} from '../services/api';
import type {
  AnalysisReviewDecision,
  ActionItem,
  CoachAction,
  EvidenceReference,
  Finding,
  PersistedAnalysisResponse,
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

function RecommendedActionCard({ action, approved, created, selected, disabled, onSelect }: { action: CoachAction; approved: boolean; created?: ActionItem; selected: boolean; disabled: boolean; onSelect: (selected: boolean) => void }) {
  return (
    <article className="detail-card detail-card--action">
      <div className="detail-card__header">
        <div>
          <div className="eyebrow">AI recommendation</div>
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
      {created ? <div className="form-feedback" role="status">Operational Action Item created · {created.status.replace('_', ' ')}</div> : approved ? <label className="action-selection"><input type="checkbox" checked={selected} disabled={disabled} onChange={(event) => onSelect(event.target.checked)} /> Select this recommendation for an operational Action Item</label> : null}
    </article>
  );
}

function AnalysisMetadata({ analysis }: { analysis: PersistedAnalysisResponse }) {
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

function ReviewPanel({
  analysis,
  note,
  onNoteChange,
  onDecision,
  onReload,
  busy,
  feedback,
  validationMessage,
}: {
  analysis: PersistedAnalysisResponse;
  note: string;
  onNoteChange: (value: string) => void;
  onDecision: (decision: AnalysisReviewDecision) => void;
  onReload: () => void;
  busy: boolean;
  feedback: { kind: 'success' | 'error' | 'conflict'; message: string } | null;
  validationMessage: string | null;
}) {
  const statusClass = analysis.review_status === 'approved'
    ? 'badge badge--positive'
    : analysis.review_status === 'changes_requested'
      ? 'badge badge--warning'
      : 'badge';

  return (
    <section
      className="analysis-review panel"
      aria-labelledby="analysis-review-title"
      aria-busy={busy}
    >
      <div className="analysis-review__header">
        <div>
          <div className="eyebrow">Human review</div>
          <h2 id="analysis-review-title">Review this saved analysis</h2>
          <p>Record an analysis-level decision. No external action is triggered.</p>
        </div>
        <span className={statusClass}>
          Current status: {readableLabel(analysis.review_status)}
        </span>
      </div>

      <dl className="analysis-review__metadata">
        <div>
          <dt>Saved review note</dt>
          <dd>{analysis.review_note || 'No review note saved.'}</dd>
        </div>
        <div>
          <dt>Reviewed</dt>
          <dd>
            {analysis.reviewed_at
              ? <time dateTime={analysis.reviewed_at}>{formatCreatedAt(analysis.reviewed_at)}</time>
              : 'Not reviewed yet'}
          </dd>
        </div>
        <div>
          <dt>Review version</dt>
          <dd>{analysis.review_version}</dd>
        </div>
      </dl>

      <label className="field-stack" htmlFor="analysis-review-note">
        Review note <span className="form-hint">Optional for approval; required when requesting changes.</span>
        <textarea
          id="analysis-review-note"
          value={note}
          maxLength={2000}
          rows={4}
          disabled={busy}
          onChange={(event) => onNoteChange(event.target.value)}
        />
      </label>
      {validationMessage && (
        <p className="analysis-review__feedback analysis-review__feedback--error" role="alert">
          {validationMessage}
        </p>
      )}

      <div className="toolbar analysis-review__actions">
        <button
          className="primary"
          type="button"
          disabled={busy}
          onClick={() => onDecision('approved')}
        >
          Approve analysis
        </button>
        <button
          className="secondary analysis-review__changes-button"
          type="button"
          disabled={busy}
          onClick={() => onDecision('changes_requested')}
        >
          Request changes
        </button>
      </div>

      {busy && (
        <p className="loading-state" role="status" aria-live="polite">
          <span className="signal-pulse" aria-hidden="true" />
          Saving review
        </p>
      )}
      {feedback?.kind === 'success' && (
        <p className="analysis-review__feedback analysis-review__feedback--success" role="status" aria-live="polite">
          {feedback.message}
        </p>
      )}
      {feedback?.kind === 'error' && (
        <p className="analysis-review__feedback analysis-review__feedback--error" role="alert">
          {feedback.message}
        </p>
      )}
      {feedback?.kind === 'conflict' && (
        <div className="analysis-review__feedback analysis-review__feedback--error" role="alert">
          <p>{feedback.message}</p>
          <button className="secondary" type="button" disabled={busy} onClick={onReload}>
            Reload saved analysis
          </button>
        </div>
      )}
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
  const [analysis, setAnalysis] = useState<PersistedAnalysisResponse | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [reviewNote, setReviewNote] = useState('');
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewFeedback, setReviewFeedback] = useState<{
    kind: 'success' | 'error' | 'conflict';
    message: string;
  } | null>(null);
  const [reviewValidation, setReviewValidation] = useState<string | null>(null);
  const reviewLock = useRef(false);
  const actionLock = useRef(false);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [selectedActionIds, setSelectedActionIds] = useState<string[]>([]);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<{ kind: 'success' | 'error' | 'conflict'; message: string } | null>(null);

  useEffect(() => {
    if (!analysisId || !UUID_PATTERN.test(analysisId)) {
      setStatus('invalid');
      setAnalysis(null);
      return;
    }

    let active = true;
    setStatus('loading');
    Promise.all([getAnalysis(analysisId), listAnalysisActions(analysisId)])
      .then(([response, actionResponse]) => {
        if (!active) return;
        setAnalysis(response);
        setReviewNote(response.review_note || '');
        setReviewFeedback(null);
        setReviewValidation(null);
        setActions(actionResponse.items);
        setSelectedActionIds([]);
        setActionFeedback(null);
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

  const submitReview = async (decision: AnalysisReviewDecision) => {
    if (!analysisId || !analysis || reviewLock.current) return;
    const normalizedNote = reviewNote.trim();
    if (decision === 'changes_requested' && !normalizedNote) {
      setReviewValidation('Add a meaningful review note before requesting changes.');
      return;
    }

    reviewLock.current = true;
    setReviewBusy(true);
    setReviewValidation(null);
    setReviewFeedback(null);
    try {
      const response = await updateAnalysisReview(analysisId, {
        review_status: decision,
        review_note: normalizedNote || null,
        expected_version: analysis.review_version,
      });
      setAnalysis((current) => current ? { ...current, ...response } : current);
      setReviewNote(response.review_note || '');
      setReviewFeedback({
        kind: 'success',
        message: decision === 'approved'
          ? 'Analysis review saved as approved.'
          : 'Analysis review saved with changes requested.',
      });
    } catch (error) {
      if (error instanceof AnalysisReviewConflictError) {
        setReviewFeedback({
          kind: 'conflict',
          message: 'This saved analysis was changed elsewhere. Reload the saved analysis before reviewing again.',
        });
      } else {
        setReviewFeedback({
          kind: 'error',
          message: 'The review could not be saved. Please try again.',
        });
      }
    } finally {
      reviewLock.current = false;
      setReviewBusy(false);
    }
  };

  const reloadAfterConflict = async () => {
    if (!analysisId || reviewLock.current) return;
    reviewLock.current = true;
    setReviewBusy(true);
    try {
      const response = await getAnalysis(analysisId);
      setAnalysis(response);
      setReviewNote(response.review_note || '');
      setReviewFeedback(null);
      setReviewValidation(null);
    } catch {
      setReviewFeedback({
        kind: 'error',
        message: 'The latest saved analysis could not be loaded. Please try again.',
      });
    } finally {
      reviewLock.current = false;
      setReviewBusy(false);
    }
  };

  const materializeSelected = async () => {
    if (!analysisId || actionLock.current || selectedActionIds.length === 0) return;
    actionLock.current = true; setActionBusy(true); setActionFeedback(null);
    try {
      const response = await materializeAnalysisActions(analysisId, { source_action_ids: selectedActionIds });
      setActions((current) => {
        const bySource = new Map(current.map((item) => [item.source_action_id, item]));
        response.items.forEach((item) => bySource.set(item.source_action_id, item));
        return Array.from(bySource.values());
      });
      setSelectedActionIds([]);
      setActionFeedback({ kind: 'success', message: `${response.created_count} Action Item${response.created_count === 1 ? '' : 's'} created; ${response.existing_count} already existed.` });
    } catch (error) {
      setActionFeedback(error instanceof ActionMaterializationConflictError
        ? { kind: 'conflict', message: 'The approval state changed. Reload the saved analysis before creating Action Items.' }
        : { kind: 'error', message: error instanceof Error ? error.message : 'The selected Action Items could not be created.' });
    } finally { actionLock.current = false; setActionBusy(false); }
  };

  const reloadActionsAndAnalysis = async () => {
    if (!analysisId || actionLock.current) return;
    actionLock.current = true; setActionBusy(true);
    try {
      const [latestAnalysis, latestActions] = await Promise.all([getAnalysis(analysisId), listAnalysisActions(analysisId)]);
      setAnalysis(latestAnalysis); setActions(latestActions.items); setSelectedActionIds([]); setActionFeedback(null);
    } catch { setActionFeedback({ kind: 'error', message: 'The latest saved analysis and Action Items could not be loaded.' }); }
    finally { actionLock.current = false; setActionBusy(false); }
  };

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

      <ReviewPanel
        analysis={analysis}
        note={reviewNote}
        onNoteChange={(value) => {
          setReviewNote(value);
          setReviewValidation(null);
        }}
        onDecision={submitReview}
        onReload={reloadAfterConflict}
        busy={reviewBusy}
        feedback={reviewFeedback}
        validationMessage={reviewValidation}
      />

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
        {analysis.review_status !== 'approved' ? <p className="form-feedback">Approve this analysis before creating operational Action Items.</p> : null}
        {analysis.recommended_actions.length > 0 ? (
          <div className="analysis-detail__cards">
            {analysis.recommended_actions.map((action) => <RecommendedActionCard action={action} approved={analysis.review_status === 'approved'} created={actions.find((item) => item.source_action_id === action.action_id)} selected={selectedActionIds.includes(action.action_id)} disabled={actionBusy} onSelect={(selected) => setSelectedActionIds((current) => selected ? [...current, action.action_id] : current.filter((id) => id !== action.action_id))} key={action.action_id} />)}
          </div>
        ) : <p className="analysis-detail__empty-subsection card">No recommended actions were stored.</p>}
        {analysis.review_status === 'approved' && analysis.recommended_actions.length > 0 ? <div className="action-materialization" aria-busy={actionBusy}><button className="primary" type="button" disabled={actionBusy || selectedActionIds.length === 0} onClick={() => void materializeSelected()}>{actionBusy ? 'Creating…' : 'Create selected actions'}</button>{actionFeedback ? <div role={actionFeedback.kind === 'success' ? 'status' : 'alert'} aria-live="polite" className={actionFeedback.kind === 'success' ? 'form-feedback' : 'form-feedback form-feedback--error'}>{actionFeedback.message}{actionFeedback.kind === 'conflict' ? <button className="secondary" type="button" onClick={() => void reloadActionsAndAnalysis()}>Reload saved analysis</button> : null}</div> : null}</div> : null}
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
