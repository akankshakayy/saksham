import { useParams, useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import {
  getApplication,
  getApplicationDocuments,
  getApplicationHistory,
  getDocument,
} from "../services/api";
import type { DocumentDetailResponse } from "../types/api";
import { useState, useEffect } from "react";
import {
  StateBadge,
  RiskBadge,
  LoadingState,
  ErrorState,
} from "../components/Badges";
import { WorkflowStepper } from "../components/WorkflowStepper";
import { DecisionSummary } from "../components/DecisionSummary";
import { DocumentEvidenceCard } from "../components/DocumentEvidenceCard";
import { VerificationComparison } from "../components/VerificationComparison";
import { EscalationBanner } from "../components/EscalationBanner";
import { DecisionExplanation } from "../components/DecisionExplanation";
import { AIRecommendationCard, PolicyDecisionCard } from "../components/DecisionCards";
import { AuditTimeline } from "../components/AuditTimeline";
import { formatTimestamp } from "../utils/format";
import "../styles/pages.css";

function useDocDetails(appId: string, docIds: string[]) {
  const [docs, setDocs] = useState<DocumentDetailResponse[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (docIds.length === 0) {
      setDocs([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all(docIds.map((did) => getDocument(appId, did)))
      .then((results) => {
        if (!cancelled) {
          setDocs(results);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDocs([]);
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [appId, docIds.join(",")]);

  return { docs, loading };
}

export function ApplicationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const {
    data: app,
    loading,
    error,
    refetch,
  } = useApi(() => getApplication(id!), [id]);

  const { data: docsSummary } = useApi(
    () => getApplicationDocuments(id!),
    [id]
  );

  const { data: history } = useApi(
    () => getApplicationHistory(id!),
    [id]
  );

  const docIds = (docsSummary || []).map((d) => d.document_id);
  const { docs: docDetails, loading: docsLoading } = useDocDetails(id!, docIds);

  if (loading) return <LoadingState message="Loading application..." />;
  if (error) return <ErrorState message={error.message} onRetry={refetch} />;
  if (!app) return <ErrorState message="Application not found." />;

  const events = history?.events || [];

  return (
    <>
      {/* SECTION 1: Application Header */}
      <div className="app-detail-header">
        <div className="app-detail-header-top">
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => navigate("/applications")}
          >
            &larr; Applications
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => navigator.clipboard.writeText(app.application_id)}
            title="Copy application ID"
          >
            Copy ID
          </button>
        </div>
        <div className="app-detail-header-main">
          <div className="app-detail-header-info">
            <h1 className="app-detail-applicant">
              {app.applicant_name || app.business_name || "Unnamed Application"}
            </h1>
            <div className="app-detail-id">
              <span className="mono">{app.application_id}</span>
            </div>
            <div className="app-detail-meta">
              {app.business_type && (
                <span className="app-detail-meta-item">{app.business_type}</span>
              )}
              <span className="app-detail-meta-item">
                Created {formatTimestamp(app.created_at)}
              </span>
              <span className="app-detail-meta-item">
                Updated {formatTimestamp(app.updated_at)}
              </span>
            </div>
          </div>
          <div className="app-detail-header-badges">
            <div className="app-detail-badge-row">
              <StateBadge state={app.current_state} />
            </div>
            {app.final_decision && (
              <div className="app-detail-badge-row">
                <span className="app-detail-badge-label">Decision</span>
                <span className={`badge ${app.final_decision === "APPROVE" ? "badge-success" : app.final_decision === "REJECT_OR_BLOCK" ? "badge-danger" : app.final_decision === "ESCALATE_TO_HUMAN" ? "badge-escalated" : "badge-warning"}`}>
                  {app.final_decision.replace(/_/g, " ")}
                </span>
              </div>
            )}
            {app.risk_level && (
              <div className="app-detail-badge-row">
                <span className="app-detail-badge-label">Risk</span>
                <RiskBadge risk={app.risk_level} />
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="page-body app-detail-body">
        {/* Escalation Banner */}
        <EscalationBanner
          currentState={app.current_state}
          retryCount={app.retry_count}
          events={events}
          riskFactors={app.risk_factors}
        />

        {/* SECTION 2: Workflow Progress */}
        <div className="detail-section">
          <div className="detail-section-title">Workflow Progress</div>
          <div className="card">
            <WorkflowStepper events={events} currentState={app.current_state} />
          </div>
        </div>

        {/* SECTION 3: Decision Summary */}
        <div className="detail-section">
          <div className="detail-section-title">Decision Summary</div>
          <DecisionSummary
            currentState={app.current_state}
            finalDecision={app.final_decision}
            riskLevel={app.risk_level}
            riskScore={app.risk_score}
          />
        </div>

        <div className="two-col">
          {/* Left Column */}
          <div>
            {/* SECTION 4: Application Information */}
            <div className="detail-section">
              <div className="detail-section-title">Application Information</div>
              <div className="card">
                <div className="detail-grid">
                  {[
                    { label: "Applicant Name", value: app.applicant_name },
                    { label: "Business Name", value: app.business_name },
                    { label: "Business Type", value: app.business_type },
                    { label: "PAN Number", value: app.pan_number, mono: true },
                    { label: "GST Number", value: app.gst_number, mono: true },
                    { label: "Phone", value: app.phone },
                    { label: "Email", value: app.email },
                    { label: "Address", value: app.address },
                  ].map((field) => (
                    <div className="detail-field" key={field.label}>
                      <span className="detail-field-label">{field.label}</span>
                      <span className={`detail-field-value${field.mono ? " mono" : ""}`}>
                        {field.value || <span className="muted">Not provided</span>}
                      </span>
                    </div>
                  ))}
                </div>
                {app.missing_fields.length > 0 && (
                  <div className="app-missing-fields">
                    <strong>Missing fields:</strong> {app.missing_fields.join(", ")}
                  </div>
                )}
              </div>
            </div>

            {/* SECTION 5: Document Evidence */}
            <div className="detail-section">
              <div className="detail-section-title">
                Document Evidence
                {docDetails.length > 0 && (
                  <span className="section-count">{docDetails.length}</span>
                )}
              </div>
              {docsLoading ? (
                <div className="doc-loading">Loading document details...</div>
              ) : docDetails.length > 0 ? (
                <div className="doc-evidence-list">
                  {docDetails.map((doc) => (
                    <DocumentEvidenceCard
                      key={doc.document_id}
                      doc={doc}
                      applicationId={app.application_id}
                    />
                  ))}
                </div>
              ) : (
                <div className="doc-empty">
                  No documents have been processed yet.
                </div>
              )}
            </div>

            {/* SECTION 6: Verification Comparison */}
            <div className="detail-section">
              <div className="detail-section-title">Verification</div>
              <div className="card">
                <VerificationComparison app={app} docs={docDetails} />
              </div>
            </div>
          </div>

          {/* Right Column */}
          <div>
            {/* SECTION 7: Risk Assessment */}
            <div className="detail-section">
              <div className="detail-section-title">Risk Assessment</div>
              <div className="card">
                <div className="risk-assessment">
                  <div className="risk-main">
                    <span className="risk-main-label">Risk Level</span>
                    <RiskBadge risk={app.risk_level} />
                  </div>
                  {app.risk_score !== null && (
                    <div className="risk-main">
                      <span className="risk-main-label">Score</span>
                      <span className="risk-score-display">
                        {app.risk_score.toFixed(2)}
                      </span>
                    </div>
                  )}
                </div>
                {app.risk_factors.length > 0 && (
                  <div className="risk-factors">
                    <span className="risk-factors-label">Risk Factors</span>
                    <ul className="risk-factors-list">
                      {app.risk_factors.map((factor, i) => (
                        <li key={i}>{factor}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {app.risk_factors.length === 0 && (
                  <div className="risk-factors">
                    <span className="risk-factors-label">Risk Factors</span>
                    <p className="risk-no-factors">None identified</p>
                  </div>
                )}
              </div>
            </div>

            {/* SECTION 8: AI Recommendation */}
            <div className="detail-section">
              <div className="detail-section-title">AI Recommendation</div>
              <AIRecommendationCard recommendation={app.recommendation} />
            </div>

            {/* SECTION 9: Final Policy Decision */}
            <div className="detail-section">
              <div className="detail-section-title">Final Policy Decision</div>
              <PolicyDecisionCard finalDecision={app.final_decision} />
            </div>

            {/* SECTION 10: Decision Explanation */}
            <div className="detail-section">
              <div className="detail-section-title">Decision Explanation</div>
              <div className="card">
                <DecisionExplanation
                  currentState={app.current_state}
                  finalDecision={app.final_decision}
                  riskLevel={app.risk_level}
                  riskFactors={app.risk_factors}
                  recommendation={app.recommendation}
                  missingFields={app.missing_fields}
                  docsCount={docDetails.length}
                  retryCount={app.retry_count}
                  events={events}
                />
              </div>
            </div>
          </div>
        </div>

        {/* SECTION 11: Audit Timeline — full width */}
        <div className="detail-section">
          <div className="detail-section-title">
            Audit Trail
            {events.length > 0 && (
              <span className="section-count">{events.length}</span>
            )}
          </div>
          <div className="card">
            <AuditTimeline events={events} />
          </div>
        </div>
      </div>
    </>
  );
}
