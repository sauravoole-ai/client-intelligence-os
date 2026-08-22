import type { AuditEntry, ReviewItem } from '../types';

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
