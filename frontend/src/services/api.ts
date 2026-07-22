import type { AnalysisResponse } from '../types';

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

function isAnalysisResponse(value: unknown): value is AnalysisResponse {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<AnalysisResponse>;
  return candidate.status === 'completed'
    && typeof candidate.analysis_id === 'string'
    && typeof candidate.engine === 'string'
    && Array.isArray(candidate.findings)
    && Array.isArray(candidate.risk_flags)
    && Array.isArray(candidate.recommended_actions);
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
