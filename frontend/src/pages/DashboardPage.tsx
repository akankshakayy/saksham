import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  listApplications,
  getApplicationHistory,
  getHealth,
} from "../services/api";
import { MetricCard } from "../components/MetricCard";
import { StateBadge, DecisionBadge, RiskBadge } from "../components/Badges";
import { LoadingState, ErrorState, EmptyState } from "../components/Badges";
import {
  formatTimestamp,
  formatEventType,
} from "../utils/format";
import type {
  ApplicationSummaryResponse,
  AuditEventResponse,
  HealthResponse,
  WorkflowState,
  RiskLevel,
} from "../types/api";
import "../styles/pages.css";

interface WorkerEvent {
  event: AuditEventResponse;
  appLabel: string;
}

export function DashboardPage() {
  const navigate = useNavigate();
  const mountedRef = useRef(true);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [apps, setApps] = useState<ApplicationSummaryResponse[]>([]);
  const [workerEvents, setWorkerEvents] = useState<WorkerEvent[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchHealth = async () => {
    try {
      const h = await getHealth();
      if (mountedRef.current) {
        setHealth(h);
        setHealthError(false);
      }
    } catch {
      if (mountedRef.current) {
        setHealth(null);
        setHealthError(true);
      }
    }
  };

  useEffect(() => {
    fetchHealth();
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);

      try {
        const listResult = await listApplications({ limit: 100, offset: 0 });
        if (cancelled) return;

        setTotalCount(listResult.total);
        setApps(listResult.applications);

        const sorted = [...listResult.applications].sort(
          (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
        );
        const recent = sorted.slice(0, 5);

        const historyResults = await Promise.allSettled(
          recent.map((a) => getApplicationHistory(a.application_id))
        );

        if (cancelled) return;

        const allEvents: WorkerEvent[] = [];
        for (let i = 0; i < historyResults.length; i++) {
          const r = historyResults[i];
          if (r.status === "fulfilled") {
            const label = recent[i].applicant_name || recent[i].application_id.slice(0, 8);
            for (const ev of r.value.events) {
              allEvents.push({ event: ev, appLabel: label });
            }
          }
        }

        allEvents.sort(
          (a, b) =>
            new Date(b.event.timestamp).getTime() -
            new Date(a.event.timestamp).getTime()
        );

        setWorkerEvents(allEvents.slice(0, 20));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load dashboard");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    run();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <LoadingState message="Loading dashboard..." />;
  if (error) return <ErrorState message={error} onRetry={() => { setError(null); setLoading(true); }} />;

  const total = totalCount;
  const approved = apps.filter((a) => a.current_state === "APPROVED").length;
  const rejected = apps.filter((a) => a.current_state === "REJECTED").length;
  const escalated = apps.filter(
    (a) => a.current_state === "ESCALATED" || a.current_state === "ESCALATED_TO_HUMAN"
  ).length;
  const moreInfo = apps.filter(
    (a) => a.current_state === "MORE_INFORMATION_REQUIRED" || a.current_state === "MISSING_INFORMATION"
  ).length;
  const processing = apps.filter(
    (a) =>
      ![
        "APPROVED", "REJECTED", "ESCALATED", "ESCALATED_TO_HUMAN",
        "FAILED", "TOOL_FAILED",
      ].includes(a.current_state)
  ).length;

  const riskCounts: Record<string, number> = { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 };
  for (const a of apps) {
    if (a.risk_level) riskCounts[a.risk_level] = (riskCounts[a.risk_level] || 0) + 1;
  }
  const riskTotal = Object.values(riskCounts).reduce((s, n) => s + n, 0);

  const stateCounts: Record<string, number> = {};
  for (const a of apps) {
    stateCounts[a.current_state] = (stateCounts[a.current_state] || 0) + 1;
  }

  const priorityApps = apps.filter(
    (a) =>
      a.current_state === "ESCALATED" ||
      a.current_state === "ESCALATED_TO_HUMAN" ||
      a.risk_level === "HIGH" ||
      a.risk_level === "CRITICAL" ||
      a.current_state === "MORE_INFORMATION_REQUIRED"
  );

  const eventIcon = (eventType: string) => {
    if (eventType.includes("APPROVED") || eventType.includes("SUCCESS")) return "\u2713";
    if (eventType.includes("REJECTED") || eventType.includes("FAILED")) return "\u2717";
    if (eventType.includes("ESCALATED")) return "\u26A0";
    if (eventType.includes("RETRY")) return "\u21BB";
    return "\u2022";
  };

  const eventVariant = (eventType: string): "success" | "danger" | "warning" | "info" => {
    if (eventType.includes("APPROVED") || eventType.includes("SUCCESS")) return "success";
    if (eventType.includes("REJECTED") || eventType.includes("FAILED")) return "danger";
    if (eventType.includes("ESCALATED")) return "warning";
    return "info";
  };

  return (
    <>
      <div className="page-header">
        <div className="dashboard-header-row">
          <div>
            <h1>Dashboard</h1>
            <p>Operational overview of the Saksham Worker</p>
          </div>
          <div className="system-health-indicator">
            <span
              className={`status-dot ${health?.status === "ok" ? "ok" : healthError ? "error" : ""}`}
              aria-label={health?.status === "ok" ? "System healthy" : "System status unknown"}
            />
            <span className="system-health-text">
              {health?.status === "ok"
                ? "SYSTEM HEALTHY"
                : healthError
                ? "SYSTEM UNAVAILABLE"
                : "CHECKING..."}
            </span>
            {health?.version && (
              <span className="system-health-version">v{health.version}</span>
            )}
            <button
              className="btn btn-sm btn-secondary"
              onClick={fetchHealth}
              aria-label="Refresh system health"
            >
              Refresh
            </button>
          </div>
        </div>
      </div>
      <div className="page-body">
        {total === 0 ? (
          <EmptyState
            title="No applications yet"
            description="Submit your first application to get started."
            action={
              <button
                className="btn btn-primary"
                onClick={() => navigate("/applications/new")}
              >
                New Application
              </button>
            }
          />
        ) : (
          <>
            <div className="detail-section">
              <div className="detail-section-title">Key Metrics</div>
              <div className="metric-grid">
                <MetricCard
                  label="Total Applications"
                  value={total}
                  subtitle="All submitted applications"
                />
                <MetricCard
                  label="Approved"
                  value={approved}
                  variant="success"
                  subtitle="Successfully verified"
                  onClick={() => navigate("/applications?state=APPROVED")}
                />
                <MetricCard
                  label="Processing"
                  value={processing}
                  variant="info"
                  subtitle="Currently in workflow"
                />
                <MetricCard
                  label="More Information"
                  value={moreInfo}
                  variant="warning"
                  subtitle="Awaiting applicant data"
                  onClick={() => navigate("/applications?state=MORE_INFORMATION_REQUIRED")}
                />
                <MetricCard
                  label="Escalated"
                  value={escalated}
                  variant="danger"
                  subtitle="Requires human review"
                  onClick={() => navigate("/applications?state=ESCALATED_TO_HUMAN")}
                />
                <MetricCard
                  label="Rejected"
                  value={rejected}
                  variant="danger"
                  subtitle="Blocked or denied"
                  onClick={() => navigate("/applications?state=REJECTED")}
                />
              </div>
            </div>

            {priorityApps.length > 0 && (
              <div className="detail-section">
                <div className="detail-section-title attention-text">
                  Attention Required ({priorityApps.length})
                </div>
                <div className="priority-list">
                  {priorityApps.slice(0, 5).map((app) => (
                    <div
                      key={app.application_id}
                      className="priority-card"
                      onClick={() => navigate(`/applications/${app.application_id}`)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ")
                          navigate(`/applications/${app.application_id}`);
                      }}
                    >
                      <div className="priority-info">
                        <span className="priority-name">
                          {app.applicant_name || app.application_id.slice(0, 8)}
                        </span>
                        <span className="priority-id">{app.application_id.slice(0, 12)}...</span>
                      </div>
                      <div className="priority-badges">
                        <StateBadge state={app.current_state} />
                        {app.risk_level && <RiskBadge risk={app.risk_level} />}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="dashboard-two-col">
              <div className="detail-section">
                <div className="card">
                  <div className="card-header">
                    <span className="card-title">Risk Distribution</span>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => navigate("/applications")}
                    >
                      View all
                    </button>
                  </div>
                  {riskTotal === 0 ? (
                    <div className="empty-mini">No risk assessments yet</div>
                  ) : (
                    <div className="risk-dist-list">
                      {(["LOW", "MEDIUM", "HIGH", "CRITICAL"] as RiskLevel[]).map((level) => {
                        const count = riskCounts[level] || 0;
                        const pct = riskTotal > 0 ? (count / riskTotal) * 100 : 0;
                        return (
                          <div key={level} className="risk-dist-row">
                            <span className="risk-dist-label">{level}</span>
                            <div className="risk-dist-bar-track">
                              <div
                                className={`risk-dist-bar-fill risk-dist-${level.toLowerCase()}`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                            <span className="risk-dist-count">{count}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>

              <div className="detail-section">
                <div className="card">
                  <div className="card-header">
                    <span className="card-title">State Distribution</span>
                  </div>
                  <div className="state-dist-list">
                    {Object.entries(stateCounts)
                      .sort(([, a], [, b]) => b - a)
                      .map(([state, count]) => (
                        <div key={state} className="state-dist-row">
                          <StateBadge state={state as WorkflowState} />
                          <span className="state-dist-count">{count}</span>
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            </div>

            <div className="detail-section">
              <div className="card">
                <div className="card-header">
                  <span className="card-title">Recent Applications</span>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => navigate("/applications")}
                  >
                    View all applications
                  </button>
                </div>
                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>Applicant</th>
                        <th>State</th>
                        <th>Risk</th>
                        <th>Decision</th>
                        <th>Updated</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(() => {
                        const sorted = [...apps].sort(
                          (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
                        );
                        return sorted.slice(0, 5).map((app) => (
                          <tr
                            key={app.application_id}
                            className="clickable"
                            onClick={() => navigate(`/applications/${app.application_id}`)}
                          >
                            <td>
                              <div className="app-table-applicant">
                                <span className="app-table-name">
                                  {app.applicant_name || "\u2014"}
                                </span>
                                {app.business_name && (
                                  <span className="app-table-business">{app.business_name}</span>
                                )}
                              </div>
                            </td>
                            <td><StateBadge state={app.current_state} /></td>
                            <td><RiskBadge risk={app.risk_level} /></td>
                            <td><DecisionBadge decision={app.final_decision} /></td>
                            <td>{formatTimestamp(app.updated_at)}</td>
                          </tr>
                        ));
                      })()}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="detail-section">
              <div className="card">
                <div className="card-header">
                  <span className="card-title">Recent Worker Activity</span>
                </div>
                {workerEvents.length === 0 ? (
                  <div className="empty-mini">No recent activity</div>
                ) : (
                  <div className="worker-activity-list">
                    {workerEvents.map((we, idx) => (
                      <div key={we.event.event_id || idx} className="worker-event-row">
                        <span className={`worker-event-icon worker-event-${eventVariant(we.event.event_type)}`}>
                          {eventIcon(we.event.event_type)}
                        </span>
                        <div className="worker-event-content">
                          <div className="worker-event-main">
                            <span className="worker-event-type">
                              {formatEventType(we.event.event_type)}
                            </span>
                            <span className="worker-event-app">{we.appLabel}</span>
                          </div>
                          <div className="worker-event-meta">
                            <span className="worker-event-time">
                              {formatTimestamp(we.event.timestamp)}
                            </span>
                            {we.event.result && we.event.result !== "none" && (
                              <span className={`worker-event-result worker-event-result-${eventVariant(we.event.event_type)}`}>
                                {we.event.result}
                              </span>
                            )}
                            {we.event.metadata && typeof we.event.metadata === "object" && (
                              <>
                                {we.event.metadata.source && (
                                  <span className="worker-event-tag">
                                    source: {String(we.event.metadata.source)}
                                  </span>
                                )}
                                {we.event.metadata.model && (
                                  <span className="worker-event-tag">
                                    model: {String(we.event.metadata.model)}
                                  </span>
                                )}
                                {we.event.metadata.recommended_action && (
                                  <span className="worker-event-tag">
                                    action: {String(we.event.metadata.recommended_action)}
                                  </span>
                                )}
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
