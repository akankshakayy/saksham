import type { AuditEventResponse, WorkflowState } from "../types/api";
import { formatTimestamp, formatState, isTerminalState } from "../utils/format";

interface WorkflowStepperProps {
  events: AuditEventResponse[];
  currentState: WorkflowState;
}

interface StepInfo {
  state: WorkflowState;
  timestamp: string | null;
  status: "completed" | "current" | "failed" | "warning" | "pending";
}

const STATE_ORDER: WorkflowState[] = [
  "RECEIVED",
  "VALIDATING",
  "VERIFYING",
  "ANALYZING_RISK",
  "DECIDING",
];

const ERROR_STATES: WorkflowState[] = [
  "TOOL_FAILED",
  "FAILED",
  "LOW_CONFIDENCE",
  "TOOL_RETRYING",
  "ESCALATED_TO_HUMAN",
  "ESCALATED",
];

const WARNING_STATES: WorkflowState[] = [
  "MISSING_INFORMATION",
  "MORE_INFORMATION_REQUIRED",
];

function buildSteps(events: AuditEventResponse[], currentState: WorkflowState): StepInfo[] {
  const seen = new Map<WorkflowState, StepInfo>();

  for (const event of events) {
    const s = event.state;
    if (!seen.has(s)) {
      seen.set(s, { state: s, timestamp: event.timestamp, status: "completed" });
    }
  }

  const terminalStates: WorkflowState[] = ["APPROVED", "REJECTED", "ESCALATED", "ESCALATED_TO_HUMAN", "FAILED"];
  const hasTerminal = terminalStates.includes(currentState);

  for (const [state, info] of seen) {
    if (state === currentState) {
      if (isTerminalState(state)) {
        info.status = "completed";
      } else {
        info.status = "current";
      }
    } else if (ERROR_STATES.includes(state)) {
      if (info.status === "completed") {
        info.status = "failed";
      }
    } else if (WARNING_STATES.includes(state)) {
      if (info.status === "completed") {
        info.status = "warning";
      }
    }
  }

  if (!seen.has(currentState) && !hasTerminal) {
    const lastEvent = events[events.length - 1];
    seen.set(currentState, {
      state: currentState,
      timestamp: lastEvent?.timestamp || null,
      status: "current",
    });
  }

  const steps: StepInfo[] = [];
  for (const s of STATE_ORDER) {
    if (seen.has(s)) steps.push(seen.get(s)!);
  }

  for (const [state, info] of seen) {
    if (!STATE_ORDER.includes(state)) {
      steps.push(info);
    }
  }

  if (steps.length > 0 && !hasTerminal) {
    const lastStep = steps[steps.length - 1];
    if (lastStep.state !== currentState && !steps.find(s => s.state === currentState)) {
      steps.push({
        state: currentState,
        timestamp: null,
        status: "current",
      });
    }
  }

  return steps;
}

function stepIcon(status: StepInfo["status"]): string {
  switch (status) {
    case "completed": return "\u2713";
    case "current": return "\u25CB";
    case "failed": return "\u2717";
    case "warning": return "\u26A0";
    case "pending": return "\u2022";
  }
}

function stepClass(status: StepInfo["status"]): string {
  return `stepper-step stepper-${status}`;
}

export function WorkflowStepper({ events, currentState }: WorkflowStepperProps) {
  const steps = buildSteps(events, currentState);

  if (steps.length === 0) {
    return (
      <div className="stepper-empty">
        No workflow events recorded yet.
      </div>
    );
  }

  return (
    <div className="workflow-stepper" role="list" aria-label="Workflow progress">
      {steps.map((step, i) => (
        <div key={step.state} className={stepClass(step.status)} role="listitem">
          <div className="stepper-connector">
            <div className="stepper-node">
              <span className="stepper-icon" aria-hidden="true">{stepIcon(step.status)}</span>
            </div>
            {i < steps.length - 1 && <div className="stepper-line" />}
          </div>
          <div className="stepper-content">
            <span className="stepper-label">{formatState(step.state)}</span>
            {step.timestamp && (
              <span className="stepper-time">{formatTimestamp(step.timestamp)}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
