import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { WhatChangedResponse } from '../types';
import { WhatChangedPanel } from './WhatChangedPanel';

const response: WhatChangedResponse = {
  client_id: 'client-1', comparison_analysis_id: 'analysis-1',
  items: [
    { signal_id: 'one', change_kind: 'new', summary: 'New pattern', evidence: [{ action_item_id: 'action-1', action_field: 'status', evidence_role: 'supports' }] },
    { signal_id: 'two', change_kind: 'recurring', summary: 'Recurring pattern', evidence: [{ action_item_id: 'action-2', action_field: 'due_at', evidence_role: 'supports' }] },
    { signal_id: 'three', change_kind: 'improving', summary: 'Improving pattern', evidence: [{ action_item_id: 'action-3', action_field: 'completed_at', evidence_role: 'resolves' }] },
    { signal_id: 'four', change_kind: 'worsening', summary: 'Worsening pattern', evidence: [{ action_item_id: 'action-4', action_field: 'status', evidence_role: 'contradicts' }] },
    { signal_id: 'five', change_kind: 'resolved', summary: 'Resolved pattern', evidence: [{ action_item_id: 'action-5', action_field: 'completion_outcome', evidence_role: 'resolves' }] },
  ],
};

describe('WhatChangedPanel', () => {
  it('renders new, recurring, improving, worsening, and resolved cards with evidence', () => {
    render(<WhatChangedPanel response={response} />);
    for (const summary of ['New pattern', 'Recurring pattern', 'Improving pattern', 'Worsening pattern', 'Resolved pattern']) expect(screen.getByText(summary)).toBeInTheDocument();
    expect(screen.getAllByText(/Evidence:/)).toHaveLength(5);
  });

  it('states insufficient history clearly', () => {
    render(<WhatChangedPanel response={{ client_id: 'client-1', comparison_analysis_id: null, items: [{ signal_id: null, change_kind: 'insufficient_history', summary: 'Insufficient approved history.', evidence: [] }] }} />);
    expect(screen.getByText(/insufficient approved history/i)).toBeInTheDocument();
  });
});
