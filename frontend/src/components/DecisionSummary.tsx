import type { WorkflowState, FinalDecision, RiskLevel } from "../types/api";
import { RiskBadge } from "./Badges";
import { formatDecision, isTerminalState } from "../utils/format";

interface DecisionSummaryProps {
  currentState: WorkflowState;
  finalDecision: FinalDecision | null;
  riskLevel: RiskLevel | null;
  riskScore: number | null;
}

function humanReviewRequired(
  currentState: WorkflowState,
  finalDecision: FinalDecision | null
): boolean {
  if (currentState === "ESCALATED_TO_HUMAN") return true;
  if (currentState === "ESCALATED") return true;
  if (finalDecision === "ESCALATE_TO_HUMAN") return true;
  return false;
}

function decisionLabel(d: FinalDecision | null): string {
  if (!d) return "Pending";
  return formatDecision(d);
}

function decisionClass(d: FinalDecision | null): string {
  if (d === "APPROVE") return "ds-value ds-success";
  if (d === "REJECT_OR_BLOCK") return "ds-value ds-danger";
  if (d === "ESCALATE_TO_HUMAN") return "ds-value ds-warning";
  if (d === "REQUEST_MORE_INFORMATION") return "ds-value ds-info";
  return "ds-value ds-muted";
}

function riskScoreBar(score: number | null): string {
  if (score === null) return "";
  if (score >= 0.7) return "risk-bar-high";
  if (score >= 0.4) return "risk-bar-medium";
  return "risk-bar-low";
}

export function DecisionSummary({
  currentState,
  finalDecision,
  riskLevel,
  riskScore,
}: DecisionSummaryProps) {
  const needsHuman = humanReviewRequired(currentState, finalDecision);
  const terminal = isTerminalState(currentState);

  return (
    <div className="decision-summary">
      <div className="ds-item">
        <span className="ds-label">Risk Level</span>
        <div className="ds-risk">
          <RiskBadge risk={riskLevel} />
          {riskScore !== null && (
            <span className="ds-risk-score">
              <span className={`risk-score-bar ${riskScoreBar(riskScore)}`} />
              <span className="risk-score-num">{riskScore.toFixed(2)}</span>
            </span>
          )}
        </div>
      </div>

      <div className="ds-divider" />

      <div className="ds-item">
        <span className="ds-label">Final Decision</span>
        <span className={decisionClass(finalDecision)}>
          {decisionLabel(finalDecision)}
        </span>
      </div>

      <div className="ds-divider" />

      <div className="ds-item">
        <span className="ds-label">Human Review</span>
        <span className={needsHuman ? "ds-value ds-warning" : "ds-value ds-muted"}>
          {needsHuman ? "Required" : terminal ? "Not required" : "Pending"}
        </span>
      </div>
    </div>
  );
}
