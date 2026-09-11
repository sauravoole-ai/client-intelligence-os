import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  AnalysisListResponse,
  AnalysisResponse,
  AnalysisReviewResponse,
  PersistedAnalysisResponse,
  Client,
  LongitudinalSignal,
  TrajectoryResponse,
  WhatChangedResponse,
  LongitudinalRefreshResponse,
} from '../types';
import {
  AnalysisReviewConflictError,
  createAnalysis,
  getAnalysis,
  listAnalyses,
  updateAnalysisReview,
  ClientConflictError,
  createClient,
  getClient,
  listClientAnalyses,
  listClients,
  ActionStatusConflictError,
  getAction,
  listActions,
  listAnalysisActions,
  listClientActions,
  listWorkspaceMembers,
  materializeAnalysisActions,
  updateActionFollowUp,
  updateActionStatus,
  getClientTrajectory,
  getClientWhatChanged,
  getLongitudinalSignal,
  refreshClientLongitudinal,
  reviewLongitudinalSignal,
  LongitudinalSignalConflictError,
} from './api';

type AuthApiContract = {
  configureApiAuthentication: (options: {
    csrfToken: string | null;
    onUnauthorized: () => void;
  }) => void;
  clearApiAuthentication: () => void;
  getAuthenticatedSession: () => Promise<{
    user_id: string;
    display_name: string | null;
    email: string | null;
    workspace_id: string;
    workspace_name: string | null;
    role: string;
    csrf_token: string;
  }>;
  logout: () => Promise<void>;
};

const authApi = await import('./api') as typeof import('./api') & AuthApiContract;

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  authApi.clearApiAuthentication?.();
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
    classification: 'ai_generated_inference',
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

const persistedAnalysisResponse: PersistedAnalysisResponse = {
  ...analysisResponse,
  client_id: null,
  review_status: 'pending_review',
  review_note: null,
  reviewed_at: null,
  review_version: 1,
};

const clientResponse: Client = {
  id: '00000000-0000-0000-0000-000000000010',
  display_name: 'Client One',
  external_reference: 'EXT-10',
  status: 'active',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
};
const actionItem = { id: 'action-item-1', analysis_id: analysisResponse.analysis_id, client_id: null, source_action_id: 'action-1', title: 'Follow up', description: 'Stored rationale', priority: 1, status: 'open' as const, linked_finding_ids: ['finding-1'], due_at: null, completed_at: null, assignee_membership_id: null, completion_outcome: null, assignee: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', version: 1 };

const reviewResponse: AnalysisReviewResponse = {
  analysis_id: analysisResponse.analysis_id,
  review_status: 'approved',
  review_note: 'Reviewed.',
  reviewed_at: '2026-01-02T00:00:00Z',
  review_version: 2,
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
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(persistedAnalysisResponse)));

    await expect(getAnalysis(analysisResponse.analysis_id)).resolves.toEqual(persistedAnalysisResponse);
  });

  it('encodes the analysis ID in the request path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(persistedAnalysisResponse));
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
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ...persistedAnalysisResponse, findings: [{}] })));

    await expect(getAnalysis(analysisResponse.analysis_id)).rejects.toThrow('invalid response');
  });

  it.each([
    ['review_status', undefined],
    ['review_status', 'unknown'],
    ['review_note', 42],
    ['reviewed_at', 42],
    ['review_version', 0],
  ])('rejects malformed persisted review field %s', async (field, value) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      ...persistedAnalysisResponse,
      [field]: value,
    })));

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

describe('updateAnalysisReview', () => {
  it('uses PUT, encodes the ID, and sends a normalized request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(reviewResponse));
    vi.stubGlobal('fetch', fetchMock);

    await updateAnalysisReview('analysis/id with spaces', {
      review_status: 'approved',
      review_note: '  Reviewed.  ',
      expected_version: 1,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/analyses/analysis%2Fid%20with%20spaces/review',
      expect.objectContaining({
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          review_status: 'approved',
          review_note: 'Reviewed.',
          expected_version: 1,
        }),
      }),
    );
  });

  it('parses a complete valid mutation response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(reviewResponse)));

    await expect(updateAnalysisReview(analysisResponse.analysis_id, {
      review_status: 'approved',
      review_note: null,
      expected_version: 1,
    })).resolves.toEqual(reviewResponse);
  });

  it.each([
    ['analysis_id', undefined],
    ['review_status', 'unknown'],
    ['review_note', 42],
    ['reviewed_at', 42],
    ['review_version', 0],
  ])('rejects malformed mutation field %s', async (field, value) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      ...reviewResponse,
      [field]: value,
    })));

    await expect(updateAnalysisReview(analysisResponse.analysis_id, {
      review_status: 'approved',
      review_note: null,
      expected_version: 1,
    })).rejects.toThrow('invalid response');
  });

  it.each([
    [404, 'not found'],
    [422, 'could not be validated'],
    [503, 'currently unavailable'],
    [500, 'unexpected error'],
  ])('uses a safe message for HTTP %s', async (status, message) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private server detail', { status })));

    const request = updateAnalysisReview(analysisResponse.analysis_id, {
      review_status: 'approved',
      review_note: null,
      expected_version: 1,
    });
    await expect(request).rejects.toThrow(message);
    await expect(updateAnalysisReview(analysisResponse.analysis_id, {
      review_status: 'approved',
      review_note: null,
      expected_version: 1,
    })).rejects.not.toThrow('private server detail');
  });

  it('exposes a typed sanitized conflict', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private conflict detail', { status: 409 })));

    await expect(updateAnalysisReview(analysisResponse.analysis_id, {
      review_status: 'approved',
      review_note: null,
      expected_version: 1,
    })).rejects.toBeInstanceOf(AnalysisReviewConflictError);
  });

  it('handles timeout without exposing internals', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((...[, init]: Parameters<typeof fetch>) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('private abort', 'AbortError')));
    })));

    const request = expect(updateAnalysisReview(analysisResponse.analysis_id, {
      review_status: 'approved',
      review_note: null,
      expected_version: 1,
    }, 10)).rejects.toThrow('timed out');
    await vi.advanceTimersByTimeAsync(10);

    await request;
  });

  it('sanitizes network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('private network detail')));

    await expect(updateAnalysisReview(analysisResponse.analysis_id, {
      review_status: 'approved',
      review_note: null,
      expected_version: 1,
    })).rejects.toThrow('Unable to reach');
    await expect(updateAnalysisReview(analysisResponse.analysis_id, {
      review_status: 'approved',
      review_note: null,
      expected_version: 1,
    })).rejects.not.toThrow('private network detail');
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

describe('client API', () => {
  it('validates client lists and rejects malformed items', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ items: [clientResponse], offset: 0, limit: 20, returned_count: 1 })));
    await expect(listClients()).resolves.toMatchObject({ items: [clientResponse] });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ items: [{ ...clientResponse, status: 'unknown' }], offset: 0, limit: 20, returned_count: 1 })));
    await expect(listClients()).rejects.toThrow('invalid response');
  });

  it('creates a client with normalized fields using POST', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(clientResponse, 201));
    vi.stubGlobal('fetch', fetchMock);
    await createClient({ display_name: '  Client One ', external_reference: ' EXT-10 ' });
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/clients', expect.objectContaining({ method: 'POST', body: JSON.stringify({ display_name: 'Client One', external_reference: 'EXT-10' }) }));
  });

  it('sanitizes duplicate conflicts and missing clients', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private', { status: 409 })));
    await expect(createClient({ display_name: 'One' })).rejects.toBeInstanceOf(ClientConflictError);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private', { status: 404 })));
    await expect(getClient('missing')).rejects.toThrow('not found');
  });

  it('gets a client and encodes its ID', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(clientResponse));
    vi.stubGlobal('fetch', fetchMock);
    await expect(getClient('id/with space')).resolves.toEqual(clientResponse);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/clients/id%2Fwith%20space', expect.any(Object));
  });

  it('validates client analysis review and client metadata', async () => {
    const linked = { ...persistedAnalysisResponse, client_id: clientResponse.id };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ items: [linked], offset: 0, limit: 20, returned_count: 1 })));
    await expect(listClientAnalyses(clientResponse.id)).resolves.toMatchObject({ items: [linked] });
  });

  it('sanitizes malformed, network, and timeout failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{', { status: 200 })));
    await expect(getClient('id')).rejects.toThrow('invalid response');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('private network')));
    await expect(getClient('id')).rejects.toThrow('Unable to reach');
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((...[, init]: Parameters<typeof fetch>) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('private abort', 'AbortError')));
    })));
    const request = expect(getClient('id', 10)).rejects.toThrow('timed out');
    await vi.advanceTimersByTimeAsync(10);
    await request;
  });
});

describe('longitudinal intelligence API', () => {
  const signal: LongitudinalSignal = {
    id: '00000000-0000-0000-0000-000000000101',
    client_id: clientResponse.id,
    canonical_key: 'sleep-consistency',
    signal_kind: 'theme',
    temporal_state: 'active',
    trend_direction: 'stable',
    summary: 'Sleep consistency is an active theme.',
    explanation: 'The approved evidence supports this theme.',
    trust_state: 'draft',
    first_observed_at: '2026-01-01T00:00:00Z',
    last_observed_at: '2026-01-02T00:00:00Z',
    observation_count: 1,
    version: 1,
    reviewed_at: null,
    evidence: [{
      analysis_id: analysisResponse.analysis_id,
      artifact_kind: 'finding',
      artifact_id: 'finding-1',
      evidence_role: 'supports',
    }],
  };

  const trajectory: TrajectoryResponse = {
    client_id: clientResponse.id,
    trusted_signals: [],
    review_required: [signal],
    action_item_aggregates: { open_count: 1, completed_count: 0 },
    deterministic_metrics: {},
  };

  const whatChanged: WhatChangedResponse = {
    client_id: clientResponse.id,
    comparison_analysis_id: analysisResponse.analysis_id,
    items: [{ signal_id: null, change_kind: 'insufficient_history', summary: 'Insufficient approved history.', evidence: [] }],
  };

  const unavailableRefresh: LongitudinalRefreshResponse = {
    processed_analysis_count: 1,
    processed_action_item_count: 0,
    created_draft_signal_count: 0,
    updated_draft_signal_count: 0,
    invalidated_trusted_signal_count: 0,
    semantic_status: 'unavailable',
  };

  it('validates controlled longitudinal response shapes', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(signal))
      .mockResolvedValueOnce(jsonResponse(trajectory))
      .mockResolvedValueOnce(jsonResponse(whatChanged));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getLongitudinalSignal(signal.id)).resolves.toEqual(signal);
    await expect(getClientTrajectory(clientResponse.id)).resolves.toEqual(trajectory);
    await expect(getClientWhatChanged(clientResponse.id)).resolves.toEqual(whatChanged);
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      `/api/v1/longitudinal-signals/${signal.id}`,
      `/api/v1/clients/${clientResponse.id}/trajectory`,
      `/api/v1/clients/${clientResponse.id}/what-changed`,
    ]);
  });

  it('maps review 409 to a longitudinal conflict error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private conflict detail', { status: 409 })));

    await expect(reviewLongitudinalSignal(signal.id, {
      action: 'approve', expected_version: 1, reason: null,
    })).rejects.toBeInstanceOf(LongitudinalSignalConflictError);
  });

  it('preserves semantic unavailability and safely maps refresh admission failures', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(unavailableRefresh));
    vi.stubGlobal('fetch', fetchMock);
    await expect(refreshClientLongitudinal(clientResponse.id)).resolves.toEqual(unavailableRefresh);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/clients/${clientResponse.id}/longitudinal-refresh`,
      expect.objectContaining({ method: 'POST' }),
    );

    for (const status of [429, 503]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private admission detail', { status })));
      await expect(refreshClientLongitudinal(clientResponse.id)).rejects.toThrow(/try again|unavailable/i);
      await expect(refreshClientLongitudinal(clientResponse.id)).rejects.not.toThrow('private admission detail');
    }
  });

  it('rejects an unexpected longitudinal evidence shape', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      ...signal,
      evidence: [{ analysis_id: analysisResponse.analysis_id, evidence_role: 'supports' }],
    })));

    await expect(getLongitudinalSignal(signal.id)).rejects.toThrow('invalid response');
  });
});

describe('action API', () => {
  it('materializes using POST and sends source IDs only', async () => {
    const response = { analysis_id: analysisResponse.analysis_id, items: [actionItem], created_count: 1, existing_count: 0 };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(response, 201)); vi.stubGlobal('fetch', fetchMock);
    await expect(materializeAnalysisActions('analysis/id', { source_action_ids: ['action-1'] })).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/analyses/analysis%2Fid/actions', expect.objectContaining({ method: 'POST', body: JSON.stringify({ source_action_ids: ['action-1'] }) }));
  });
  it('rejects malformed materialization', async () => { vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ items: [{}], created_count: 1, existing_count: 0 }))); await expect(materializeAnalysisActions('id', { source_action_ids: ['a'] })).rejects.toThrow('invalid response'); });
  it('lists and encodes status/client filters', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [actionItem], offset: 0, limit: 20, returned_count: 1 })); vi.stubGlobal('fetch', fetchMock);
    await listActions({ status: 'in_progress', client_id: 'client/id' });
    expect(fetchMock.mock.calls[0][0]).toContain('status=in_progress'); expect(fetchMock.mock.calls[0][0]).toContain('client_id=client%2Fid');
  });
  it('serializes every queue and uses the browser zone only for calendar queues', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ items: [], offset: 0, limit: 20, returned_count: 0 }))); vi.stubGlobal('fetch', fetchMock);
    const browserTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    for (const queue of ['open', 'due_today', 'overdue', 'upcoming', 'completed', 'no_due_date'] as const) await listActions({ queue });
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls[0]).toContain('queue=open'); expect(urls[0]).not.toContain('time_zone=');
    expect(urls[1]).toContain('queue=due_today'); expect(urls[1]).toContain(`time_zone=${encodeURIComponent(browserTimeZone)}`);
    expect(urls[3]).toContain('queue=upcoming'); expect(urls[3]).toContain(`time_zone=${encodeURIComponent(browserTimeZone)}`);
    expect(urls[2]).not.toContain('time_zone='); expect(urls[4]).not.toContain('time_zone='); expect(urls[5]).not.toContain('time_zone=');
  });
  it('serializes queue secondary filters and omits absent values', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], offset: 0, limit: 20, returned_count: 0 })); vi.stubGlobal('fetch', fetchMock);
    await listActions({ queue: 'due_today', time_zone: 'Asia/Kolkata', status: 'open', client_id: 'client/id', assignee_membership_id: 'member/id' });
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain('queue=due_today'); expect(url).toContain('time_zone=Asia%2FKolkata'); expect(url).toContain('status=open'); expect(url).toContain('client_id=client%2Fid'); expect(url).toContain('assignee_membership_id=member%2Fid');
    expect(url).not.toContain('undefined'); expect(url).not.toContain('null');
  });
  it('lists workspace members and preserves nullable display data', async () => {
    const response = { items: [{ membership_id: 'member-1', display_name: 'Ada', email: null, role: 'member' }, { membership_id: 'member-2', display_name: null, email: 'member@example.test', role: 'owner' }] };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(response)); vi.stubGlobal('fetch', fetchMock);
    await expect(listWorkspaceMembers()).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/workspace/members', expect.objectContaining({ credentials: 'same-origin' }));
    expect(new Headers(fetchMock.mock.calls[0][1].headers).has('X-CSRF-Token')).toBe(false);
  });
  it('rejects malformed workspace member and Action Item responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ items: [{ membership_id: 'member-1', display_name: 'Ada', email: null }] })));
    await expect(listWorkspaceMembers()).rejects.toThrow('invalid response');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ...actionItem, assignee_membership_id: undefined })));
    await expect(getAction(actionItem.id)).rejects.toThrow('invalid response');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ...actionItem, assignee: { membership_id: 'member-1', display_name: null, email: null, role: 'member', status: 'unknown' } })));
    await expect(getAction(actionItem.id)).rejects.toThrow('invalid response');
  });
  it('sends complete follow-up PUT bodies and preserves API errors', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(actionItem)); vi.stubGlobal('fetch', fetchMock);
    await updateActionFollowUp(actionItem.id, { assignee_membership_id: null, due_at: null, expected_version: 3 });
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/actions/action-item-1/follow-up', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ assignee_membership_id: null, due_at: null, expected_version: 3 }) }));
    fetchMock.mockResolvedValueOnce(new Response('private', { status: 409 })); await expect(updateActionFollowUp('id', { assignee_membership_id: 'member-1', due_at: '2026-09-02T09:30:00+05:30', expected_version: 4 })).rejects.toBeInstanceOf(ActionStatusConflictError);
    fetchMock.mockResolvedValueOnce(new Response('private', { status: 422 })); await expect(updateActionFollowUp('id', { assignee_membership_id: null, due_at: null, expected_version: 4 })).rejects.toThrow('could not be validated');
  });
  it('encodes action, analysis, and client IDs', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(actionItem)); vi.stubGlobal('fetch', fetchMock); await getAction('item/id'); expect(fetchMock.mock.calls[0][0]).toContain('item%2Fid');
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ items: [], offset: 0, limit: 100, returned_count: 0 }))); await listAnalysisActions('analysis/id'); await listClientActions('client/id'); expect(fetchMock.mock.calls[1][0]).toContain('analysis%2Fid'); expect(fetchMock.mock.calls[2][0]).toContain('client%2Fid');
  });
  it('updates status using PUT and expected version', async () => {
    const updated = { ...actionItem, status: 'completed' as const, version: 2, completed_at: '2026-01-02T00:00:00Z' }; const fetchMock = vi.fn().mockResolvedValue(jsonResponse(updated)); vi.stubGlobal('fetch', fetchMock);
    await expect(updateActionStatus(actionItem.id, { status: 'completed', completion_outcome: 'Resolved', expected_version: 1 })).resolves.toEqual(updated);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/actions/action-item-1/status', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ status: 'completed', completion_outcome: 'Resolved', expected_version: 1 }) }));
  });
  it('preserves null and omitted completion outcomes for non-completed status updates', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(actionItem))); vi.stubGlobal('fetch', fetchMock);
    await updateActionStatus(actionItem.id, { status: 'open', completion_outcome: null, expected_version: 2 });
    await updateActionStatus(actionItem.id, { status: 'open', expected_version: 3 });
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ body: JSON.stringify({ status: 'open', completion_outcome: null, expected_version: 2 }) }));
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({ body: JSON.stringify({ status: 'open', expected_version: 3 }) }));
  });
  it('represents conflict safely and sanitizes HTTP failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private', { status: 409 }))); await expect(updateActionStatus('id', { status: 'open', expected_version: 1 })).rejects.toBeInstanceOf(ActionStatusConflictError);
    for (const status of [404, 422, 503]) { vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private detail', { status }))); await expect(getAction('id')).rejects.not.toThrow('private detail'); }
  });
  it('sanitizes malformed, network, and timeout failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ...actionItem, linked_finding_ids: null }))); await expect(getAction('id')).rejects.toThrow('invalid response');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('private network'))); await expect(getAction('id')).rejects.toThrow('Unable to reach');
    vi.useFakeTimers(); vi.stubGlobal('fetch', vi.fn((...[, init]: Parameters<typeof fetch>) => new Promise((_resolve, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('private', 'AbortError')))))); const request = expect(getAction('id', 10)).rejects.toThrow('timed out'); await vi.advanceTimersByTimeAsync(10); await request;
  });
});

describe('auth-aware API behavior', () => {
  const session = {
    user_id: 'user-1',
    display_name: 'Ada Lovelace',
    email: 'ada@example.com',
    workspace_id: 'workspace-1',
    workspace_name: 'Atlas Coaching',
    role: 'owner',
    csrf_token: 'csrf-for-current-session',
  };

  it('reads auth/me with same-origin credentials and never sends CSRF on GET', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(session));
    vi.stubGlobal('fetch', fetchMock);

    await expect(authApi.getAuthenticatedSession()).resolves.toEqual(session);

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/me',
      expect.objectContaining({ credentials: 'same-origin' }),
    );
    expect(new Headers(fetchMock.mock.calls[0][1].headers).has('X-CSRF-Token')).toBe(false);
  });

  it('adds the in-memory session CSRF token to POST and PUT requests only', async () => {
    authApi.configureApiAuthentication({ csrfToken: session.csrf_token, onUnauthorized: vi.fn() });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(clientResponse, 201))
      .mockResolvedValueOnce(jsonResponse({ ...actionItem, status: 'completed', version: 2, completed_at: '2026-01-02T00:00:00Z' }))
      .mockResolvedValueOnce(jsonResponse(actionItem))
      .mockResolvedValueOnce(jsonResponse({ items: [], offset: 0, limit: 20, returned_count: 0 }));
    vi.stubGlobal('fetch', fetchMock);

    await createClient({ display_name: 'Ada Client' });
    await updateActionStatus(actionItem.id, { status: 'completed', expected_version: 1 });
    await updateActionFollowUp(actionItem.id, { assignee_membership_id: null, due_at: null, expected_version: 1 });
    await listClients();

    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(new Headers(fetchMock.mock.calls[2][1].headers).get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(new Headers(fetchMock.mock.calls[3][1].headers).has('X-CSRF-Token')).toBe(false);
  });

  it('invalidates on protected 401s but preserves the authenticated state for 403s', async () => {
    const onUnauthorized = vi.fn();
    authApi.configureApiAuthentication({ csrfToken: session.csrf_token, onUnauthorized });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(null, { status: 401 })));

    await expect(listClients()).rejects.toThrow();
    expect(onUnauthorized).toHaveBeenCalledOnce();

    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(null, { status: 403 })));
    await expect(listClients()).rejects.toThrow();
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it('posts logout with CSRF and does not report success when logout fails', async () => {
    authApi.configureApiAuthentication({ csrfToken: session.csrf_token, onUnauthorized: vi.fn() });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ status: 'logged_out' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(authApi.logout()).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/logout',
      expect.objectContaining({ method: 'POST', credentials: 'same-origin' }),
    );
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('X-CSRF-Token')).toBe(session.csrf_token);

    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(null, { status: 503 })));
    await expect(authApi.logout()).rejects.toThrow();
  });
});
