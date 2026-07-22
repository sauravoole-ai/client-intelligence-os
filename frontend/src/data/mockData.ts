import type { AuditEntry, ClientRecord, ReviewItem } from '../types';

export const clients: ClientRecord[] = [
  {
    id: 'anon-001',
    reference: 'ANON-001',
    attention: 'High',
    engagement: 'Active',
    period: 'Week 12',
    reviews: 3,
    nextAction: 'Review fatigue escalation',
    coach: 'Mina R.',
    updatedAt: '2h ago',
    fallback: true,
  },
  {
    id: 'anon-002',
    reference: 'ANON-002',
    attention: 'Elevated',
    engagement: 'Watch',
    period: 'Week 11',
    reviews: 1,
    nextAction: 'Confirm meal plan',
    coach: 'Ari L.',
    updatedAt: '5h ago',
    fallback: false,
  },
  {
    id: 'anon-003',
    reference: 'ANON-003',
    attention: 'Steady',
    engagement: 'Needs support',
    period: 'Week 10',
    reviews: 2,
    nextAction: 'Re-engage with routine',
    coach: 'Jonas P.',
    updatedAt: 'Yesterday',
    fallback: false,
  },
];

export const reviewQueue: ReviewItem[] = [
  {
    id: 'rev-1',
    title: 'Fatigue escalation path',
    category: 'sleep',
    severity: 'high',
    status: 'pending',
    coach: 'Mina R.',
    updatedAt: '15m ago',
    evidenceCount: 4,
  },
  {
    id: 'rev-2',
    title: 'Nutrition adherence review',
    category: 'nutrition_adherence',
    severity: 'medium',
    status: 'edited',
    coach: 'Ari L.',
    updatedAt: '42m ago',
    evidenceCount: 3,
  },
  {
    id: 'rev-3',
    title: 'Risk flag follow-up',
    category: 'symptoms_stress',
    severity: 'high',
    status: 'pending',
    coach: 'Jules S.',
    updatedAt: '1h ago',
    evidenceCount: 5,
  },
];

export const auditHistory: AuditEntry[] = [
  {
    id: 'audit-1',
    actor: 'Mina R.',
    action: 'Approved',
    entity: 'Sleep pattern',
    timestamp: '2026-07-22 09:18',
    previousState: 'Pending',
    newState: 'Approved',
    reason: 'Evidence matched client report',
    engine: 'deterministic_evidence_baseline_v1',
    promptVersion: 'deterministic-baseline-v1',
  },
  {
    id: 'audit-2',
    actor: 'Ari L.',
    action: 'Edited',
    entity: 'Nutrition adherence',
    timestamp: '2026-07-22 08:41',
    previousState: 'Pending',
    newState: 'Edited',
    reason: 'Clarified incomplete meal tracking',
    engine: 'deterministic_evidence_baseline_v1',
    promptVersion: 'deterministic-baseline-v1',
  },
];

export const overviewMetrics = {
  attentionCount: 4,
  pendingReviews: 6,
  followUpsDue: 3,
  reviewTimeSaved: '14h/wk',
  completionRate: '87%',
  workload: 'Balanced',
};

export const activityFeed = [
  'Deterministic fallback active for 3 analyses',
  'High attention queue updated',
  'Review bundle for ANON-001 prepared',
];
