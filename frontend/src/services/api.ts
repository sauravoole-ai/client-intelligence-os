import type {
  AnalysisListResponse,
  AnalysisResponse,
  AnalysisReviewRequest,
  AnalysisReviewResponse,
  CoachAction,
  EvidenceReference,
  Finding,
  PersistedAnalysisResponse,
  RiskFlag,
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export interface CreateAnalysisPayload {
  conversation: string;
  client_reference?: string | null;
  analysis_period?: string | null;
  engine_mode?: 'auto' | 'llm' | 'deterministic';
}

function normalizeError(response: Response, fallback: string) {
  if (response.status === 422) return 'The submitted conversation could not be validated.';
  if (response.status === 503) return 'The intelligence engine is currently unavailable.';
  if (response.status >= 500) return 'The server returned an unexpected error.';
  return fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object';
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function isReviewStatus(value: unknown) {
  return value === 'pending'
    || value === 'approved'
    || value === 'edited'
    || value === 'rejected';
}

function isAnalysisReviewStatus(value: unknown) {
  return value === 'pending_review'
    || value === 'approved'
    || value === 'changes_requested';
}

function isEvidenceReference(value: unknown): value is EvidenceReference {
  return isRecord(value)
    && typeof value.message_id === 'string'
    && typeof value.day === 'string'
    && typeof value.speaker === 'string'
    && typeof value.quote === 'string';
}

function isFinding(value: unknown): value is Finding {
  return isRecord(value)
    && typeof value.finding_id === 'string'
    && typeof value.category === 'string'
    && typeof value.title === 'string'
    && typeof value.statement === 'string'
    && typeof value.classification === 'string'
    && typeof value.confidence === 'number'
    && Array.isArray(value.evidence)
    && value.evidence.every(isEvidenceReference)
    && isReviewStatus(value.review_status);
}

function isRiskFlag(value: unknown): value is RiskFlag {
  return isRecord(value)
    && typeof value.risk_id === 'string'
    && typeof value.title === 'string'
    && typeof value.severity === 'string'
    && typeof value.rationale === 'string'
    && typeof value.classification === 'string'
    && typeof value.confidence === 'number'
    && Array.isArray(value.evidence)
    && value.evidence.every(isEvidenceReference)
    && isReviewStatus(value.review_status);
}

function isCoachAction(value: unknown): value is CoachAction {
  return isRecord(value)
    && typeof value.action_id === 'string'
    && typeof value.priority === 'number'
    && typeof value.action === 'string'
    && typeof value.rationale === 'string'
    && typeof value.classification === 'string'
    && isStringArray(value.linked_finding_ids)
    && Array.isArray(value.evidence)
    && value.evidence.every(isEvidenceReference)
    && isReviewStatus(value.review_status);
}

function isAnalysisResponse(value: unknown): value is AnalysisResponse {
  return isRecord(value)
    && value.status === 'completed'
    && typeof value.analysis_id === 'string'
    && typeof value.created_at === 'string'
    && (value.client_reference === undefined
      || value.client_reference === null
      || typeof value.client_reference === 'string')
    && typeof value.analysis_period === 'string'
    && isFinding(value.weekly_summary)
    && Array.isArray(value.findings)
    && value.findings.every(isFinding)
    && Array.isArray(value.risk_flags)
    && value.risk_flags.every(isRiskFlag)
    && Array.isArray(value.recommended_actions)
    && value.recommended_actions.every(isCoachAction)
    && isStringArray(value.missing_information)
    && typeof value.engine === 'string'
    && typeof value.prompt_version === 'string'
    && isStringArray(value.validation_warnings)
    && (value.fallback_reason === undefined
      || value.fallback_reason === null
      || typeof value.fallback_reason === 'string');
}

function isAnalysisListResponse(value: unknown): value is AnalysisListResponse {
  return isRecord(value)
    && Array.isArray(value.items)
    && value.items.every(isAnalysisResponse)
    && typeof value.offset === 'number'
    && Number.isInteger(value.offset)
    && value.offset >= 0
    && typeof value.limit === 'number'
    && Number.isInteger(value.limit)
    && value.limit >= 1
    && value.limit <= 100
    && typeof value.returned_count === 'number'
    && Number.isInteger(value.returned_count)
    && value.returned_count === value.items.length;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isAnalysisReviewResponse(value: unknown): value is AnalysisReviewResponse {
  return isRecord(value)
    && typeof value.analysis_id === 'string'
    && isAnalysisReviewStatus(value.review_status)
    && isNullableString(value.review_note)
    && isNullableString(value.reviewed_at)
    && Number.isInteger(value.review_version)
    && typeof value.review_version === 'number'
    && value.review_version >= 1;
}

function isPersistedAnalysisResponse(
  value: unknown,
): value is PersistedAnalysisResponse {
  return isAnalysisResponse(value)
    && isAnalysisReviewResponse(value);
}

class ReviewApiError extends Error {}

export class AnalysisReviewConflictError extends Error {
  constructor() {
    super('This saved analysis was changed elsewhere. Reload it before reviewing again.');
    this.name = 'AnalysisReviewConflictError';
  }
}

export async function createAnalysis(payload: CreateAnalysisPayload, timeoutMs = 15_000): Promise<AnalysisResponse> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE_URL}/analyses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(normalizeError(response, `Request failed with ${response.status}`));
    }

    const data: unknown = await response.json();
    if (!isAnalysisResponse(data)) throw new Error('The analysis service returned an invalid response.');
    return data;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('The analysis request timed out. Please retry.');
    }
    if (error instanceof SyntaxError) throw new Error('The analysis service returned an invalid response.');
    if (error instanceof Error) {
      throw error;
    }
    throw new Error('Unable to reach the analysis service.');
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function getAnalysis(
  analysisId: string,
  timeoutMs = 15_000,
): Promise<PersistedAnalysisResponse> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(
      `${API_BASE_URL}/analyses/${encodeURIComponent(analysisId)}`,
      { signal: controller.signal },
    );

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('The requested analysis was not found.');
      }
      throw new Error(normalizeError(response, 'The saved analysis could not be retrieved.'));
    }

    const data: unknown = await response.json();
    if (!isPersistedAnalysisResponse(data)) {
      throw new Error('The analysis service returned an invalid response.');
    }
    return data;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('The analysis request timed out. Please retry.');
    }
    if (error instanceof SyntaxError) {
      throw new Error('The analysis service returned an invalid response.');
    }
    if (error instanceof Error) throw error;
    throw new Error('Unable to reach the analysis service.');
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function updateAnalysisReview(
  analysisId: string,
  request: AnalysisReviewRequest,
  timeoutMs = 15_000,
): Promise<AnalysisReviewResponse> {
  const normalizedNote = request.review_note?.trim() || null;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(
      `${API_BASE_URL}/analyses/${encodeURIComponent(analysisId)}/review`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...request,
          review_note: normalizedNote,
        }),
        signal: controller.signal,
      },
    );

    if (!response.ok) {
      if (response.status === 409) throw new AnalysisReviewConflictError();
      if (response.status === 404) {
        throw new ReviewApiError('The requested analysis was not found.');
      }
      if (response.status === 422) {
        throw new ReviewApiError('The review request could not be validated.');
      }
      if (response.status === 503) {
        throw new ReviewApiError('The analysis review service is currently unavailable.');
      }
      throw new ReviewApiError('The server returned an unexpected error.');
    }

    const data: unknown = await response.json();
    if (!isAnalysisReviewResponse(data)) {
      throw new ReviewApiError('The analysis service returned an invalid response.');
    }
    return data;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('The analysis review request timed out. Please retry.');
    }
    if (error instanceof SyntaxError) {
      throw new Error('The analysis service returned an invalid response.');
    }
    if (
      error instanceof ReviewApiError
      || error instanceof AnalysisReviewConflictError
    ) {
      throw error;
    }
    throw new Error('Unable to reach the analysis review service.');
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function listAnalyses(
  options: { offset?: number; limit?: number } = {},
  timeoutMs = 15_000,
): Promise<AnalysisListResponse> {
  const offset = options.offset ?? 0;
  const limit = options.limit ?? 20;
  if (!Number.isInteger(offset) || offset < 0) {
    throw new Error('offset must be an integer of at least 0');
  }
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('limit must be an integer between 1 and 100');
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(
      `${API_BASE_URL}/analyses?offset=${offset}&limit=${limit}`,
      { signal: controller.signal },
    );

    if (!response.ok) {
      throw new Error(normalizeError(response, 'The saved analyses could not be retrieved.'));
    }

    const data: unknown = await response.json();
    if (!isAnalysisListResponse(data)) {
      throw new Error('The analysis service returned an invalid response.');
    }
    return data;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('The analysis request timed out. Please retry.');
    }
    if (error instanceof SyntaxError) {
      throw new Error('The analysis service returned an invalid response.');
    }
    if (error instanceof Error) throw error;
    throw new Error('Unable to reach the analysis service.');
  } finally {
    window.clearTimeout(timeout);
  }
}
