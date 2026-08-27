import type { WorkflowState, FinalDecision, RiskLevel } from "../types/api";

const STATE_GROUPS: Record<string, string> = {
  APPROVED: "badge-approved",
  REJECTED: "badge-rejected",
  ESCALATED: "badge-escalated",
  ESCALATED_TO_HUMAN: "badge-escalated",
  FAILED: "badge-failed",
  RECEIVED: "badge-processing",
  VALIDATING: "badge-processing",
  VERIFYING: "badge-processing",
  ANALYZING_RISK: "badge-processing",
  DECIDING: "badge-processing",
  TOOL_RETRYING: "badge-pending",
  LOW_CONFIDENCE: "badge-pending",
  TOOL_FAILED: "badge-danger",
  MISSING_INFORMATION: "badge-warning",
  MORE_INFORMATION_REQUIRED: "badge-warning",
};

const DECISION_GROUPS: Record<string, string> = {
  APPROVE: "badge-success",
  REQUEST_MORE_INFORMATION: "badge-warning",
  ESCALATE_TO_HUMAN: "badge-escalated",
  REJECT_OR_BLOCK: "badge-danger",
};

const RISK_GROUPS: Record<string, string> = {
  LOW: "badge-risk-low",
  MEDIUM: "badge-risk-medium",
  HIGH: "badge-risk-high",
  CRITICAL: "badge-risk-critical",
};

export function stateBadgeClass(state: WorkflowState): string {
  return `badge ${STATE_GROUPS[state] || "badge-neutral"}`;
}

export function decisionBadgeClass(decision: FinalDecision | null): string {
  if (!decision) return "badge badge-neutral";
  return `badge ${DECISION_GROUPS[decision] || "badge-neutral"}`;
}

export function riskBadgeClass(risk: RiskLevel | null): string {
  if (!risk) return "badge badge-neutral";
  return `badge ${RISK_GROUPS[risk] || "badge-neutral"}`;
}

export function confidenceClass(value: number): string {
  if (value >= 0.7) return "confidence-high";
  if (value >= 0.4) return "confidence-medium";
  return "confidence-low";
}

export function formatState(state: WorkflowState): string {
  return state
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatDecision(decision: FinalDecision | null): string {
  if (!decision) return "Pending";
  return decision
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatRisk(risk: RiskLevel | null): string {
  if (!risk) return "Not assessed";
  return risk.charAt(0) + risk.slice(1).toLowerCase();
}

export function formatTimestamp(ts: string): string {
  const date = new Date(ts);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatEventType(eventType: string): string {
  return eventType
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function isTerminalState(state: WorkflowState): boolean {
  return ["APPROVED", "REJECTED", "ESCALATED", "ESCALATED_TO_HUMAN", "FAILED"].includes(state);
}

export function stateCategory(
  state: WorkflowState
): "terminal" | "processing" | "waiting" | "error" {
  if (isTerminalState(state)) return "terminal";
  if (["TOOL_RETRYING", "LOW_CONFIDENCE"].includes(state)) return "waiting";
  if (["TOOL_FAILED", "FAILED"].includes(state)) return "error";
  return "processing";
}
