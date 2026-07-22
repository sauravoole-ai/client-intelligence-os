import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAnalysis } from './api';

afterEach(() => vi.restoreAllMocks());

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
