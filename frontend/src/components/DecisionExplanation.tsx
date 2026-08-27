import type {
  WorkflowState,
  FinalDecision,
  AuditEventResponse,
  RecommendationResponse,
} from "../types/api";

interface DecisionExplanationProps {
  currentState: WorkflowState;
  finalDecision: FinalDecision | null;
  riskLevel: string | null;
  riskFactors: string[];
  recommendation: RecommendationResponse | null;
  missingFields: string[];
  docsCount: number;
  retryCount: number;
  events: AuditEventResponse[];
}

interface ExplanationLine {
  text: string;
  type: "positive" | "negative" | "neutral";
}

function buildExplanation({
  currentState,
  riskLevel,
  riskFactors,
  recommendation,
  missingFields,
  docsCount,
  retryCount,
  events,
}: DecisionExplanationProps): ExplanationLine[] {
  const lines: ExplanationLine[] = [];

  const hasValidation = events.some(
    (e) => e.event_type === "TOOL_EXECUTION" && e.action === "validate_application"
  );
  if (hasValidation) {
    lines.push({ text: "Application validation passed", type: "positive" });
  }

  if (docsCount > 0) {
    const docEvents = events.filter(
      (e) => e.event_type === "TOOL_EXECUTION" && e.action?.includes("document")
    );
    const anyFailed = docEvents.some((e) => e.result === "ALL_FAILED" || e.result === "ERROR");
    if (anyFailed) {
      lines.push({ text: "Document processing encountered failures", type: "negative" });
    } else {
      lines.push({ text: `${docsCount} document(s) processed successfully`, type: "positive" });
    }
  } else {
    lines.push({ text: "No documents were processed", type: "neutral" });
  }

  const hasComparison = events.some(
    (e) => e.event_type === "COMPARISON"
  );
  if (hasComparison) {
    const compEvent = events.find((e) => e.event_type === "COMPARISON");
    const overallMatch = compEvent?.metadata?.overall_match;
    if (overallMatch === true) {
      lines.push({ text: "Extracted identity fields matched application data", type: "positive" });
    } else if (overallMatch === false) {
      lines.push({ text: "Some extracted fields did not match application data", type: "negative" });
    } else {
      lines.push({ text: "Verification comparison completed", type: "neutral" });
    }
  }

  if (missingFields.length > 0) {
    lines.push({
      text: `Missing fields: ${missingFields.join(", ")}`,
      type: "negative",
    });
  }

  if (riskLevel) {
    if (riskLevel === "LOW") {
      lines.push({ text: "Risk assessed as LOW", type: "positive" });
    } else if (riskLevel === "CRITICAL") {
      lines.push({ text: "Risk assessed as CRITICAL", type: "negative" });
    } else if (riskLevel === "HIGH") {
      lines.push({ text: "Risk assessed as HIGH", type: "negative" });
    } else {
      lines.push({ text: `Risk assessed as ${riskLevel}`, type: "neutral" });
    }
  }

  if (riskFactors.length > 0) {
    for (const factor of riskFactors) {
      lines.push({ text: `Risk factor: ${factor}`, type: "negative" });
    }
  }

  if (recommendation) {
    lines.push({
      text: `AI recommendation: ${recommendation.recommended_action} (confidence: ${Math.round(recommendation.confidence * 100)}%)`,
      type: "neutral",
    });
  }

  if (retryCount > 0) {
    lines.push({
      text: `Processing retried ${retryCount} time(s)`,
      type: retryCount >= 3 ? "negative" : "neutral",
    });
  }

  if (currentState === "ESCALATED_TO_HUMAN") {
    lines.push({ text: "Autonomous processing stopped — human review required", type: "negative" });
  } else if (currentState === "APPROVED") {
    lines.push({ text: "Policy allowed approval", type: "positive" });
  } else if (currentState === "REJECTED") {
    lines.push({ text: "Policy rejected the application", type: "negative" });
  } else if (currentState === "MORE_INFORMATION_REQUIRED") {
    lines.push({ text: "Additional information required before proceeding", type: "neutral" });
  }

  return lines;
}

function lineIcon(type: ExplanationLine["type"]): string {
  if (type === "positive") return "\u2713";
  if (type === "negative") return "\u2717";
  return "\u2022";
}

function lineClass(type: ExplanationLine["type"]): string {
  return `explain-line explain-${type}`;
}

export function DecisionExplanation(props: DecisionExplanationProps) {
  const lines = buildExplanation(props);

  if (lines.length === 0) {
    return (
      <div className="explain-empty">
        Insufficient information to generate explanation.
      </div>
    );
  }

  return (
    <div className="decision-explanation">
      <div className="explain-header">Why this decision?</div>
      <ul className="explain-list">
        {lines.map((line, i) => (
          <li key={i} className={lineClass(line.type)}>
            <span className="explain-icon" aria-hidden="true">{lineIcon(line.type)}</span>
            {line.text}
          </li>
        ))}
      </ul>
    </div>
  );
}
