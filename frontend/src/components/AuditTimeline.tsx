import { useState } from "react";
import type { AuditEventResponse } from "../types/api";
import { formatTimestamp, formatEventType } from "../utils/format";

interface AuditTimelineProps {
  events: AuditEventResponse[];
}

function eventCategory(result: string): string {
  if (result === "SUCCESS" || result === "REUSED") return "event-success";
  if (result === "ERROR" || result === "ALL_FAILED") return "event-error";
  return "event-info";
}

function safeMetadataDisplay(metadata: Record<string, unknown>): Record<string, string> {
  const safe: Record<string, string> = {};
  const blocked = ["api_key", "authorization", "token", "secret", "password", "env"];
  for (const [key, value] of Object.entries(metadata)) {
    if (blocked.some((b) => key.toLowerCase().includes(b))) continue;
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      safe[key] = String(value);
    } else if (Array.isArray(value)) {
      safe[key] = value.join(", ");
    } else if (typeof value === "object" && value !== null) {
      safe[key] = JSON.stringify(value);
    }
  }
  return safe;
}

function TimelineEvent({ event }: { event: AuditEventResponse }) {
  const [expanded, setExpanded] = useState(false);
  const meta = safeMetadataDisplay(event.metadata);
  const hasMeta = Object.keys(meta).length > 0;

  return (
    <div className={`timeline-event ${eventCategory(event.result)}`}>
      <button
        className="timeline-event-header"
        onClick={() => hasMeta && setExpanded(!expanded)}
        aria-expanded={hasMeta ? expanded : undefined}
        type="button"
      >
        <span className="timeline-event-action">
          {formatEventType(event.event_type)}
        </span>
        <span className={`badge badge-neutral timeline-result-badge`}>
          {event.result}
        </span>
        <span className="timeline-event-time">
          {formatTimestamp(event.timestamp)}
        </span>
        {hasMeta && (
          <span className="timeline-expand-icon" aria-hidden="true">
            {expanded ? "\u25B2" : "\u25BC"}
          </span>
        )}
      </button>
      <div className="timeline-event-detail">
        {event.action}
        {event.metadata && typeof event.metadata.from_state === "string" && typeof event.metadata.to_state === "string" && (
          <span className="timeline-transition">
            {event.metadata.from_state} &#x2192; {event.metadata.to_state}
          </span>
        )}
      </div>
      {expanded && hasMeta && (
        <div className="timeline-metadata">
          {Object.entries(meta).map(([key, value]) => (
            <div key={key} className="timeline-meta-row">
              <span className="timeline-meta-key">{key.replace(/_/g, " ")}</span>
              <span className="timeline-meta-value mono">{value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function AuditTimeline({ events }: AuditTimelineProps) {
  if (events.length === 0) {
    return <p className="timeline-empty">No events recorded.</p>;
  }

  return (
    <div className="timeline">
      {events.map((event) => (
        <TimelineEvent key={event.event_id} event={event} />
      ))}
    </div>
  );
}
