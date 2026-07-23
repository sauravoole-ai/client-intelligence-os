export type ReviewStatus = 'pending' | 'approved' | 'edited' | 'rejected';

export interface EvidenceReference {
  message_id: string;
  day: string;
  speaker: string;
  quote: string;
}

export interface Finding {
  finding_id: string;
  category: string;
  title: string;
  statement: string;
  classification: string;
  confidence: number;
  evidence: EvidenceReference[];
  review_status: ReviewStatus;
}

export interface RiskFlag {
  risk_id: string;
  title: string;
  severity: string;
  rationale: string;
  classification: string;
  confidence: number;
  evidence: EvidenceReference[];
  review_status: ReviewStatus;
}

export interface CoachAction {
  action_id: string;
  priority: number;
  action: string;
  rationale: string;
  classification: string;
  linked_finding_ids: string[];
  evidence: EvidenceReference[];
  review_status: ReviewStatus;
}

export interface AnalysisResponse {
  analysis_id: string;
  status: string;
  created_at: string;
  client_reference?: string | null;
  analysis_period: string;
  weekly_summary: Finding;
  findings: Finding[];
  risk_flags: RiskFlag[];
  recommended_actions: CoachAction[];
  missing_information: string[];
  engine: string;
  prompt_version: string;
  validation_warnings: string[];
  fallback_reason?: string | null;
}

export interface AnalysisListResponse {
  items: AnalysisResponse[];
  offset: number;
  limit: number;
  returned_count: number;
}

export type AnalysisReviewStatus =
  | 'pending_review'
  | 'approved'
  | 'changes_requested';

export type AnalysisReviewDecision = Exclude<
  AnalysisReviewStatus,
  'pending_review'
>;

export interface AnalysisReviewRequest {
  review_status: AnalysisReviewDecision;
  review_note: string | null;
  expected_version: number;
}

export interface AnalysisReviewResponse {
  analysis_id: string;
  review_status: AnalysisReviewStatus;
  review_note: string | null;
  reviewed_at: string | null;
  review_version: number;
}

export interface PersistedAnalysisResponse extends AnalysisResponse {
  review_status: AnalysisReviewStatus;
  review_note: string | null;
  reviewed_at: string | null;
  review_version: number;
}

export interface ClientRecord {
  id: string;
  reference: string;
  attention: 'High' | 'Elevated' | 'Steady';
  engagement: 'Active' | 'Watch' | 'Needs support';
  period: string;
  reviews: number;
  nextAction: string;
  coach: string;
  updatedAt: string;
  fallback: boolean;
}

export interface ReviewItem {
  id: string;
  title: string;
  category: string;
  severity: string;
  status: ReviewStatus;
  coach: string;
  updatedAt: string;
  evidenceCount: number;
}

export interface AuditEntry {
  id: string;
  actor: string;
  action: string;
  entity: string;
  timestamp: string;
  previousState: string;
  newState: string;
  reason: string;
  engine: string;
  promptVersion: string;
}
