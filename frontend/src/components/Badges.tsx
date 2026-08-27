import type { WorkflowState, FinalDecision, RiskLevel } from "../types/api";
import {
  stateBadgeClass,
  decisionBadgeClass,
  riskBadgeClass,
  formatState,
  formatDecision,
  formatRisk,
} from "../utils/format";

export function StateBadge({ state }: { state: WorkflowState }) {
  return <span className={stateBadgeClass(state)}>{formatState(state)}</span>;
}

export function DecisionBadge({ decision }: { decision: FinalDecision | null }) {
  return <span className={decisionBadgeClass(decision)}>{formatDecision(decision)}</span>;
}

export function RiskBadge({ risk }: { risk: RiskLevel | null }) {
  return <span className={riskBadgeClass(risk)}>{formatRisk(risk)}</span>;
}

export function ConfidenceIndicator({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const cls = value >= 0.7 ? "confidence-high" : value >= 0.4 ? "confidence-medium" : "confidence-low";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div className="confidence-bar">
        <div
          className={`confidence-bar-fill ${cls}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)" }}>
        {pct}%
      </span>
    </div>
  );
}

export function LoadingState({ message = "Loading..." }: { message?: string }) {
  return (
    <div className="loading-container">
      <div className="spinner" />
      <span>{message}</span>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="error-container">
      <h3>Something went wrong</h3>
      <p>{message}</p>
      {onRetry && (
        <button className="btn btn-secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title = "Nothing here yet",
  description,
  action,
}: {
  title?: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty-container">
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}
