import type { WorkflowState, AuditEventResponse } from "../types/api";

interface EscalationBannerProps {
  currentState: WorkflowState;
  retryCount: number;
  events: AuditEventResponse[];
  riskFactors: string[];
}

function findEscalationReason(
  events: AuditEventResponse[],
  currentState: WorkflowState
): string {
  if (currentState === "ESCALATED_TO_HUMAN") {
    const retryEvents = events.filter(
      (e) => e.event_type === "TOOL_EXECUTION" && e.result === "ALL_FAILED"
    );
    if (retryEvents.length > 0) {
      return "Document processing failed after the configured retry limit.";
    }
    const lowConf = events.filter(
      (e) => e.metadata?.state === "LOW_CONFIDENCE" || e.action?.includes("low_confidence")
    );
    if (lowConf.length > 0) {
      return "Processing confidence remained below threshold after retries.";
    }
    return "Autonomous processing was stopped. Human review required.";
  }

  if (currentState === "ESCALATED") {
    return "Case has been escalated for human review.";
  }

  return "Further action requires human review.";
}

function findAttemptCount(events: AuditEventResponse[]): number {
  let maxAttempt = 0;
  for (const event of events) {
    if (
      event.event_type === "TOOL_EXECUTION" &&
      typeof event.metadata?.attempt === "number"
    ) {
      maxAttempt = Math.max(maxAttempt, event.metadata.attempt as number);
    }
  }
  return maxAttempt;
}

export function EscalationBanner({
  currentState,
  retryCount,
  events,
  riskFactors,
}: EscalationBannerProps) {
  if (currentState !== "ESCALATED_TO_HUMAN" && currentState !== "ESCALATED") {
    return null;
  }

  const reason = findEscalationReason(events, currentState);
  const attempts = findAttemptCount(events) || retryCount;

  return (
    <div className="escalation-banner" role="alert">
      <div className="escalation-banner-icon" aria-hidden="true">!</div>
      <div className="escalation-banner-content">
        <div className="escalation-banner-title">Human Review Required</div>
        <div className="escalation-banner-text">
          Saksham has stopped autonomous processing.
        </div>
        <div className="escalation-banner-detail">
          <span className="escalation-label">Reason:</span> {reason}
        </div>
        {attempts > 0 && (
          <div className="escalation-banner-detail">
            <span className="escalation-label">Attempts:</span> {attempts}
          </div>
        )}
        {riskFactors.length > 0 && currentState === "ESCALATED_TO_HUMAN" && (
          <div className="escalation-banner-detail">
            <span className="escalation-label">Risk factors:</span>{" "}
            {riskFactors.join("; ")}
          </div>
        )}
        <div className="escalation-banner-footer">
          Further action requires human review.
        </div>
      </div>
    </div>
  );
}
