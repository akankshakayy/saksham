import type { RecommendationResponse, FinalDecision } from "../types/api";
import { ConfidenceIndicator, DecisionBadge } from "./Badges";

interface AIRecommendationCardProps {
  recommendation: RecommendationResponse | null;
}

export function AIRecommendationCard({ recommendation }: AIRecommendationCardProps) {
  if (!recommendation) {
    return (
      <div className="card">
        <div className="card-header">
          <span className="card-title">AI Recommendation</span>
        </div>
        <p style={{ color: "var(--color-text-muted)", fontSize: 13 }}>
          No recommendation available.
        </p>
      </div>
    );
  }

  return (
    <div className="card recommendation-card">
      <div className="card-header">
        <span className="card-title">AI Recommendation</span>
        <DecisionBadge decision={recommendation.recommended_action} />
      </div>
      <div className="detail-grid">
        <div className="detail-field">
          <span className="detail-field-label">Confidence</span>
          <ConfidenceIndicator value={recommendation.confidence} />
        </div>
        <div className="detail-field">
          <span className="detail-field-label">Source</span>
          <span className="detail-field-value mono">{recommendation.source}</span>
        </div>
        {recommendation.model && (
          <div className="detail-field">
            <span className="detail-field-label">Model</span>
            <span className="detail-field-value mono">{recommendation.model}</span>
          </div>
        )}
      </div>
      <div style={{ marginTop: 12 }}>
        <span className="detail-field-label">Reason</span>
        <p style={{ fontSize: 13, marginTop: 4 }}>{recommendation.reason}</p>
      </div>
      {recommendation.evidence.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <span className="detail-field-label">Evidence</span>
          <ul style={{ fontSize: 13, marginTop: 4, paddingLeft: 16 }}>
            {recommendation.evidence.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

interface PolicyDecisionCardProps {
  finalDecision: FinalDecision | null;
}

function policyDecisionClass(d: FinalDecision | null): string {
  if (d === "REJECT_OR_BLOCK") return "policy-card rejected";
  if (d === "ESCALATE_TO_HUMAN") return "policy-card escalated";
  return "policy-card";
}

function formatDecisionLabel(d: FinalDecision | null): string {
  if (!d) return "Pending";
  return d
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function PolicyDecisionCard({ finalDecision }: PolicyDecisionCardProps) {
  return (
    <div className={`card ${policyDecisionClass(finalDecision)}`}>
      <div className="card-header">
        <span className="card-title">Final Policy Decision</span>
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>
        {formatDecisionLabel(finalDecision)}
      </div>
      <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
        <strong>Authority:</strong> Deterministic Policy
      </div>
      <p className="policy-note">
        The AI recommendation is advisory. Deterministic policy has final decision authority.
      </p>
    </div>
  );
}
