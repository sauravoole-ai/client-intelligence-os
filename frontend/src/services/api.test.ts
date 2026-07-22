import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AnalysisListResponse, AnalysisResponse } from '../types';
import { createAnalysis, getAnalysis, listAnalyses } from './api';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const finding = {
  finding_id: 'finding-1',
  category: 'sleep',
  title: 'Sleep',
  statement: 'The client reported sleep.',
  classification: 'client_reported_information',
  confidence: 0.9,
  evidence: [{ message_id: 'msg-1', day: 'Day 1', speaker: 'Client', quote: 'Slept 5 hours.' }],
  review_status: 'pending' as const,
};

const analysisResponse: AnalysisResponse = {
  analysis_id: '00000000-0000-0000-0000-000000000001',
  status: 'completed',
  created_at: '2026-01-01T00:00:00Z',
  client_reference: 'ANON-001',
  analysis_period: 'Day 1',
  weekly_summary: finding,
  findings: [finding],
  risk_flags: [{
    risk_id: 'risk-1',
    title: 'Fatigue',
    severity: 'high',
    rationale: 'Follow-up is warranted.',
    classification: 'ai_generated_inference',
    confidence: 0.8,
    evidence: [],
    review_status: 'pending',
  }],
  recommended_actions: [{
    action_id: 'action-1',
    priority: 1,
    action: 'Follow up.',
    rationale: 'Fatigue was reported.',
    linked_finding_ids: ['finding-1'],
    evidence: [],
    review_status: 'pending',
  }],
  missing_information: ['Complete sleep log'],
  engine: 'deterministic_evidence_baseline_v1',
  prompt_version: 'deterministic-baseline-v1',
  validation_warnings: [],
  fallback_reason: null,
};

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('createAnalysis', () => {
  it('uses a safe message for validation failures without exposing response content', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('provider detail', { status: 422 })));

    await expect(createAnalysis({ conversation: 'Client: a sufficiently long message', engine_mode: 'deterministic' }))
      .rejects.toThrow('could not be validated');
    await expect(createAnalysis({ conversation: 'Client: a sufficiently long message', engine_mode: 'deterministic' }))
      .rejects.not.toThrow('provider detail');
  });

  it('rejects a malformed success response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'completed' }), {
      status: 201,
      headers: { 'Content-Type': 'application/json' },
    })));

    await expect(createAnalysis({ conversation: 'Client: a sufficiently long message', engine_mode: 'deterministic' }))
      .rejects.toThrow('invalid response');
  });
});

describe('getAnalysis', () => {
  it('retrieves and validates an analysis', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(analysisResponse)));

    await expect(getAnalysis(analysisResponse.analysis_id)).resolves.toEqual(analysisResponse);
  });

  it('encodes the analysis ID in the request path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(analysisResponse));
    vi.stubGlobal('fetch', fetchMock);

    await getAnalysis('analysis/id with spaces');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/analyses/analysis%2Fid%20with%20spaces',
      expect.any(Object),
    );
  });

  it('uses a safe message for a missing analysis', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private detail', { status: 404 })));

    await expect(getAnalysis('missing')).rejects.toThrow('The requested analysis was not found.');
    await expect(getAnalysis('missing')).rejects.not.toThrow('private detail');
  });

  it('rejects a malformed detail response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ...analysisResponse, findings: [{}] })));

    await expect(getAnalysis(analysisResponse.analysis_id)).rejects.toThrow('invalid response');
  });

  it('handles request timeouts', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((...[, init]: Parameters<typeof fetch>) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    })));

    const request = expect(getAnalysis(analysisResponse.analysis_id, 10))
      .rejects.toThrow('timed out');
    await vi.advanceTimersByTimeAsync(10);

    await request;
  });

  it('sanitizes unavailable-service responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('raw database detail', { status: 503 })));

    await expect(getAnalysis(analysisResponse.analysis_id)).rejects.toThrow('currently unavailable');
    await expect(getAnalysis(analysisResponse.analysis_id)).rejects.not.toThrow('raw database detail');
  });
});

describe('listAnalyses', () => {
  const listResponse: AnalysisListResponse = {
    items: [analysisResponse],
    offset: 0,
    limit: 20,
    returned_count: 1,
  };

  it('retrieves and validates a list', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(listResponse)));

    await expect(listAnalyses()).resolves.toEqual(listResponse);
  });

  it('uses default offset and limit query parameters', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(listResponse));
    vi.stubGlobal('fetch', fetchMock);

    await listAnalyses();

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/analyses?offset=0&limit=20',
      expect.any(Object),
    );
  });

  it('uses custom offset and limit query parameters', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      ...listResponse,
      offset: 5,
      limit: 10,
    }));
    vi.stubGlobal('fetch', fetchMock);

    await listAnalyses({ offset: 5, limit: 10 });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/analyses?offset=5&limit=10',
      expect.any(Object),
    );
  });

  it('supports an empty list', async () => {
    const emptyResponse = { items: [], offset: 0, limit: 20, returned_count: 0 };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(emptyResponse)));

    await expect(listAnalyses()).resolves.toEqual(emptyResponse);
  });

  it('rejects malformed pagination metadata', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ...listResponse, returned_count: 2 })));

    await expect(listAnalyses()).rejects.toThrow('invalid response');
  });

  it('rejects a malformed item', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      ...listResponse,
      items: [{ ...analysisResponse, weekly_summary: null }],
    })));

    await expect(listAnalyses()).rejects.toThrow('invalid response');
  });

  it.each([
    [{ offset: -1 }, 'offset'],
    [{ limit: 0 }, 'limit'],
    [{ limit: 101 }, 'limit'],
  ] as const)('rejects invalid options before fetch', async (options, message) => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(listAnalyses(options)).rejects.toThrow(message);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
