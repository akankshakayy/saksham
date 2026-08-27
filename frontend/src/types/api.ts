export type WorkflowState =
  | "RECEIVED"
  | "VALIDATING"
  | "MISSING_INFORMATION"
  | "MORE_INFORMATION_REQUIRED"
  | "VERIFYING"
  | "ANALYZING_RISK"
  | "DECIDING"
  | "APPROVED"
  | "ESCALATED"
  | "REJECTED"
  | "FAILED"
  | "TOOL_RETRYING"
  | "LOW_CONFIDENCE"
  | "TOOL_FAILED"
  | "ESCALATED_TO_HUMAN";

export type FinalDecision =
  | "APPROVE"
  | "REQUEST_MORE_INFORMATION"
  | "ESCALATE_TO_HUMAN"
  | "REJECT_OR_BLOCK";

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface HealthResponse {
  status: string;
  version: string;
}

export interface SubmitApplicationRequest {
  applicant_name?: string | null;
  business_name?: string | null;
  business_type?: string | null;
  pan_number?: string | null;
  gst_number?: string | null;
  address?: string | null;
  phone?: string | null;
  email?: string | null;
  documents?: DocumentInput[];
  metadata?: Record<string, unknown>;
}

export interface DocumentInput {
  document_type: string;
  file_path?: string | null;
  raw_text?: string | null;
  metadata?: Record<string, unknown>;
}

export interface SubmitApplicationResponse {
  application_id: string;
  state: WorkflowState;
  message: string;
}

export interface RecommendationResponse {
  recommended_action: FinalDecision;
  confidence: number;
  risk_level: RiskLevel;
  reason: string;
  evidence: string[];
  source: string;
  model: string | null;
}

export interface ApplicationStatusResponse {
  application_id: string;
  current_state: WorkflowState;
  applicant_name: string | null;
  business_name: string | null;
  business_type: string | null;
  pan_number: string | null;
  gst_number: string | null;
  address: string | null;
  phone: string | null;
  email: string | null;
  missing_fields: string[];
  retry_count: number;
  final_decision: FinalDecision | null;
  risk_level: RiskLevel | null;
  risk_score: number | null;
  risk_factors: string[];
  recommendation: RecommendationResponse | null;
  created_at: string;
  updated_at: string;
}

export interface AuditEventResponse {
  event_id: string;
  application_id: string;
  timestamp: string;
  state: WorkflowState;
  event_type: string;
  actor: string;
  action: string;
  result: string;
  metadata: Record<string, unknown>;
}

export interface WorkflowHistoryResponse {
  application_id: string;
  events: AuditEventResponse[];
}

export interface ApplicationSummaryResponse {
  application_id: string;
  applicant_name: string | null;
  business_name: string | null;
  current_state: WorkflowState;
  final_decision: FinalDecision | null;
  risk_level: RiskLevel | null;
  risk_score: number | null;
  created_at: string;
  updated_at: string;
}

export interface ListApplicationsResponse {
  applications: ApplicationSummaryResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface DocumentUploadResponse {
  document_id: string;
  application_id: string;
  document_type: string;
  original_filename: string;
  processing_status: string;
  overall_confidence: number;
  ocr_confidence: number;
  field_extraction_confidence: number;
  extracted_fields: Record<string, unknown>;
  processing_method: string;
  error_code: string | null;
  error_message: string | null;
}

export interface DocumentSummaryResponse {
  document_id: string;
  application_id: string;
  document_type: string;
  original_filename: string;
  processing_status: string;
  overall_confidence: number;
  ocr_confidence: number;
  field_extraction_confidence: number;
  processing_method: string;
  created_at: string;
  processed_at: string;
}

export interface DocumentDetailResponse {
  document_id: string;
  application_id: string;
  document_type: string;
  original_filename: string;
  processing_status: string;
  overall_confidence: number;
  ocr_confidence: number;
  field_extraction_confidence: number;
  extracted_fields: Record<string, unknown>;
  processing_method: string;
  error_code: string | null;
  error_message: string | null;
  attempt_count: number;
  created_at: string;
  processed_at: string;
}

export interface RawTextResponse {
  document_id: string;
  application_id: string;
  raw_text: string;
  character_count: number;
}

export interface ErrorResponse {
  error_code: string;
  message: string;
}
