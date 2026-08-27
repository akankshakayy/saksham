import { useParams, useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import {
  getApplication,
  getDocument,
  getDocumentRawText,
} from "../services/api";
import type { DocumentDetailResponse } from "../types/api";
import {
  ConfidenceIndicator,
  LoadingState,
  ErrorState,
} from "../components/Badges";
import { CopyButton } from "../components/CopyButton";
import { formatTimestamp } from "../utils/format";
import "../styles/pages.css";

interface ExtractedField {
  value: string | null;
  status: string;
  confidence: number;
  source_label: string | null;
}

function isExtractedField(v: unknown): v is ExtractedField {
  return (
    typeof v === "object" &&
    v !== null &&
    "value" in v &&
    "status" in v
  );
}

function formatFieldValue(raw: unknown): string {
  if (raw === null || raw === undefined) return "\u2014";
  if (isExtractedField(raw)) {
    return raw.value !== null && raw.value !== undefined ? String(raw.value) : "\u2014";
  }
  if (typeof raw === "object") return JSON.stringify(raw);
  return String(raw);
}

function fieldConfidence(raw: unknown): number | null {
  if (isExtractedField(raw)) return raw.confidence;
  return null;
}

function statusDisplay(status: string): {
  text: string;
  icon: string;
  className: string;
  ariaLabel: string;
} {
  switch (status) {
    case "completed":
      return {
        text: "Processed",
        icon: "\u2713",
        className: "doc-status-ok",
        ariaLabel: "Document processed successfully",
      };
    case "failed":
      return {
        text: "Failed",
        icon: "\u2717",
        className: "doc-status-fail",
        ariaLabel: "Document processing failed",
      };
    case "processing":
      return {
        text: "Processing",
        icon: "\u25CB",
        className: "doc-status-processing",
        ariaLabel: "Document is being processed",
      };
    default:
      return {
        text: status.replace(/_/g, " "),
        icon: "\u2022",
        className: "doc-status-pending",
        ariaLabel: `Document status: ${status}`,
      };
  }
}

function clampConfidence(val: number | null | undefined): number {
  if (val === null || val === undefined || isNaN(val)) return 0;
  return Math.max(0, Math.min(100, Math.round(val * 100)));
}

const EXTRACTED_FIELD_LABELS: Record<string, string> = {
  pan_number: "PAN",
  gst_number: "GSTIN",
  phone: "Phone",
  email: "Email",
  name: "Name",
  address: "Address",
  date_of_birth: "Date of Birth",
  registration_number: "Registration",
  business_name: "Business Name",
  applicant_name: "Applicant Name",
};

export function DocumentDetailPage() {
  const { id, documentId } = useParams<{ id: string; documentId: string }>();
  const navigate = useNavigate();

  const {
    data: doc,
    loading,
    error,
    refetch,
  } = useApi(() => getDocument(id!, documentId!), [id, documentId]);

  const { data: rawText, loading: rawTextLoading } = useApi(
    () => getDocumentRawText(id!, documentId!),
    [id, documentId]
  );

  const { data: app } = useApi(() => getApplication(id!), [id]);

  if (loading) return <LoadingState message="Loading document..." />;
  if (error) {
    const isNotFound = error.message.includes("not found") || error.message.includes("404");
    return (
      <div className="page-body">
        <ErrorState
          message={isNotFound ? "Document not found." : error.message}
          onRetry={isNotFound ? undefined : refetch}
        />
        <div style={{ marginTop: 16, textAlign: "center" }}>
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/applications")}
          >
            Back to Applications
          </button>
        </div>
      </div>
    );
  }
  if (!doc) return <ErrorState message="Document not found." />;

  const status = statusDisplay(doc.processing_status);
  const extractedEntries = Object.entries(doc.extracted_fields);
  const hasFields = extractedEntries.length > 0;
  const isFailed = doc.processing_status === "failed";
  const isLowConfidence =
    doc.processing_status !== "failed" && doc.overall_confidence < 0.4;

  return (
    <>
      {/* SECTION 1: Document Header */}
      <div className="doc-detail-header">
        <div className="doc-detail-header-top">
          <div className="doc-detail-nav-row">
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => navigate(`/applications/${id}`)}
            >
              &larr; Back to Application
            </button>
            <div className="doc-detail-nav-actions">
              <CopyButton text={doc.document_id} label="Copy Doc ID" />
              <CopyButton text={doc.application_id} label="Copy App ID" />
            </div>
          </div>
        </div>
        <div className="doc-detail-header-main">
          <div className="doc-detail-header-info">
            <div className="doc-detail-type-badge">{doc.document_type.replace(/_/g, " ")}</div>
            <h1 className="doc-detail-filename">{doc.original_filename}</h1>
            <div className="doc-detail-id-row">
              <span className="doc-detail-id-label">Document</span>
              <span className="mono doc-detail-id-value">{doc.document_id}</span>
            </div>
            <div className="doc-detail-id-row">
              <span className="doc-detail-id-label">Application</span>
              <button
                className="doc-detail-link mono"
                onClick={() => navigate(`/applications/${doc.application_id}`)}
              >
                {doc.application_id}
              </button>
            </div>
            {doc.created_at && (
              <div className="doc-detail-meta">
                <span>Created {formatTimestamp(doc.created_at)}</span>
                {doc.processed_at && (
                  <span>Processed {formatTimestamp(doc.processed_at)}</span>
                )}
              </div>
            )}
          </div>

          {/* SECTION 2: Processing Status */}
          <div className="doc-detail-status-block" role="status" aria-label={status.ariaLabel}>
            <span className={`doc-detail-status-icon ${status.className}`} aria-hidden="true">
              {status.icon}
            </span>
            <div className="doc-detail-status-content">
              <span className={`doc-detail-status-text ${status.className}`}>
                {status.text}
              </span>
              {doc.attempt_count > 1 && (
                <span className="doc-detail-attempts">
                  Attempt {doc.attempt_count}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="page-body doc-detail-body">
        {/* SECTION 8: Document Errors */}
        {isFailed && (
          <div className="doc-detail-error-banner" role="alert">
            <div className="doc-detail-error-icon" aria-hidden="true">\u2717</div>
            <div className="doc-detail-error-content">
              <div className="doc-detail-error-title">Document Processing Failed</div>
              {doc.error_code && (
                <div className="doc-detail-error-code">Error: {doc.error_code}</div>
              )}
              {doc.error_message && (
                <div className="doc-detail-error-msg">{doc.error_message}</div>
              )}
            </div>
          </div>
        )}

        {/* SECTION 9: Low Confidence Warning */}
        {isLowConfidence && (
          <div className="doc-detail-low-confidence" role="alert">
            <div className="doc-detail-low-conf-icon" aria-hidden="true">\u26A0</div>
            <div className="doc-detail-low-conf-content">
              <div className="doc-detail-low-conf-title">Low Confidence</div>
              <p className="doc-detail-low-conf-text">
                Automated verification may not be sufficient. Review the extracted
                fields and OCR text carefully.
              </p>
            </div>
          </div>
        )}

        <div className="two-col">
          {/* Left Column */}
          <div>
            {/* SECTION 3: Confidence Breakdown */}
            <div className="detail-section">
              <div className="detail-section-title">Confidence Breakdown</div>
              <div className="card">
                <div className="doc-conf-grid">
                  {[
                    { label: "Overall", value: doc.overall_confidence },
                    { label: "OCR", value: doc.ocr_confidence },
                    { label: "Field Extraction", value: doc.field_extraction_confidence },
                  ].map(({ label, value }) => (
                    <div className="doc-conf-item" key={label}>
                      <span className="doc-conf-label">{label}</span>
                      <div className="doc-conf-value-row">
                        <span className="doc-conf-pct mono">
                          {clampConfidence(value)}%
                        </span>
                        <ConfidenceIndicator value={value} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* SECTION 4: Processing Method */}
            <div className="detail-section">
              <div className="detail-section-title">Processing Method</div>
              <div className="card">
                <div className="doc-method-value mono">
                  {doc.processing_method || "\u2014"}
                </div>
              </div>
            </div>

            {/* SECTION 5: Extracted Evidence */}
            <div className="detail-section">
              <div className="detail-section-title">
                Extracted Evidence
                {hasFields && (
                  <span className="section-count">{extractedEntries.length}</span>
                )}
              </div>
              {hasFields ? (
                <div className="card">
                  <div className="doc-evidence-grid">
                    {extractedEntries.map(([key, value]) => {
                      const displayValue = formatFieldValue(value);
                      const conf = fieldConfidence(value);
                      return (
                        <div className="doc-evidence-row" key={key}>
                          <div className="doc-evidence-row-header">
                            <span className="doc-evidence-field-label">
                              {EXTRACTED_FIELD_LABELS[key] || key.replace(/_/g, " ")}
                            </span>
                            {displayValue !== "\u2014" && (
                              <CopyButton text={displayValue} label="Copy" className="btn-xs" />
                            )}
                          </div>
                          <span className="doc-evidence-field-value mono">
                            {displayValue}
                          </span>
                          {conf !== null && (
                            <span className="doc-evidence-confidence">
                              {Math.round(conf * 100)}% confidence
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className="card doc-empty-fields">
                  No fields were extracted from this document.
                </div>
              )}
            </div>

            {/* SECTION 6: Verification Context */}
            <div className="detail-section">
              <div className="detail-section-title">Verification Context</div>
              <div className="card">
                {app ? (
                  <VerificationContext
                    doc={doc}
                    appPan={app.pan_number}
                    appGst={app.gst_number}
                    appPhone={app.phone}
                    appEmail={app.email}
                    appName={app.applicant_name}
                    appAddress={app.address}
                    onNavigateToApp={() =>
                      navigate(`/applications/${doc.application_id}`)
                    }
                  />
                ) : (
                  <p className="doc-empty-fields">
                    Application data unavailable. Verification comparison is
                    available on the Application Detail page.
                  </p>
                )}
              </div>
            </div>

            {/* SECTION 10: Document Reuse */}
            <div className="detail-section">
              <div className="doc-reuse-note">
                Processed document results are persisted for reuse.
              </div>
            </div>
          </div>

          {/* Right Column */}
          <div>
            {/* SECTION 7: Raw OCR Text */}
            <div className="detail-section">
              <div className="detail-section-title">
                OCR Text
                {rawText && rawText.character_count > 0 && (
                  <span className="section-count">
                    {rawText.character_count.toLocaleString()} characters
                  </span>
                )}
              </div>
              <div className="card">
                {rawTextLoading ? (
                  <div className="doc-ocr-loading">Loading OCR text...</div>
                ) : rawText && rawText.raw_text ? (
                  <>
                    <div className="doc-ocr-toolbar">
                      <CopyButton text={rawText.raw_text} label="Copy text" />
                    </div>
                    <pre
                      className="doc-ocr-text"
                      role="region"
                      aria-label="OCR text"
                    >
                      {rawText.raw_text}
                    </pre>
                  </>
                ) : (
                  <div className="doc-empty-fields">
                    {isFailed
                      ? "OCR text is unavailable for failed documents."
                      : "No OCR text available."}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Verification Context — inline comparison for this document          */
/* ------------------------------------------------------------------ */

interface VCProps {
  doc: DocumentDetailResponse;
  appPan: string | null;
  appGst: string | null;
  appPhone: string | null;
  appEmail: string | null;
  appName: string | null;
  appAddress: string | null;
  onNavigateToApp: () => void;
}

function VerificationContext({
  doc,
  appPan,
  appGst,
  appPhone,
  appEmail,
  appName,
  appAddress,
  onNavigateToApp,
}: VCProps) {
  function normalize(v: string | null): string {
    return (v || "").trim().toUpperCase().replace(/\s+/g, " ");
  }

  function getDocVal(fieldKey: string): string | null {
    const raw = doc.extracted_fields[fieldKey];
    if (!raw) return null;
    if (isExtractedField(raw)) {
      return raw.value !== null ? String(raw.value) : null;
    }
    if (typeof raw === "string" || typeof raw === "number") return String(raw);
    return null;
  }

  const fields = [
    { key: "pan_number", label: "PAN", appVal: appPan },
    { key: "gst_number", label: "GSTIN", appVal: appGst },
    { key: "phone", label: "Phone", appVal: appPhone },
    { key: "email", label: "Email", appVal: appEmail },
    { key: "name", label: "Name", appVal: appName },
    { key: "address", label: "Address", appVal: appAddress },
  ];

  const rows = fields
    .map((f) => {
      const docVal = getDocVal(f.key);
      const appNorm = normalize(f.appVal);
      const docNorm = normalize(docVal);
      let result: "match" | "mismatch" | "partial" | "missing" = "missing";
      if (appNorm && docNorm && appNorm === docNorm) result = "match";
      else if (appNorm && docNorm && appNorm !== docNorm) result = "mismatch";
      else if (appNorm || docNorm) result = "partial";
      return { label: f.label, docVal, appVal: f.appVal, result };
    })
    .filter((r) => r.result !== "missing");

  if (rows.length === 0) {
    return (
      <p className="doc-empty-fields">
        Insufficient data for comparison. Provide application data and document
        fields to enable verification.
      </p>
    );
  }

  const matchCount = rows.filter((r) => r.result === "match").length;
  const mismatchCount = rows.filter((r) => r.result === "mismatch").length;

  return (
    <div className="doc-verification">
      <div className="doc-verification-summary">
        <span className="doc-vc-match">{matchCount} matched</span>
        {mismatchCount > 0 && (
          <span className="doc-vc-mismatch">{mismatchCount} mismatched</span>
        )}
        <span className="doc-vc-total">{rows.length} compared</span>
      </div>
      <div className="doc-verification-rows">
        {rows.map((row) => (
          <div className="doc-vc-row" key={row.label}>
            <span className="doc-vc-label">{row.label}</span>
            <span className="doc-vc-val mono">{row.docVal || "\u2014"}</span>
            <span className="doc-vc-arrow" aria-hidden="true">{"\u2192"}</span>
            <span className="doc-vc-val mono">{row.appVal || "\u2014"}</span>
            <span className={`doc-vc-result doc-vc-${row.result}`}>
              {row.result === "match" && "\u2713 Match"}
              {row.result === "mismatch" && "\u2717 Mismatch"}
              {row.result === "partial" && "\u2014 Partial"}
            </span>
          </div>
        ))}
      </div>
      <button
        className="btn btn-secondary btn-sm doc-vc-link"
        onClick={onNavigateToApp}
      >
        Full verification on Application Detail {"\u2192"}
      </button>
    </div>
  );
}
