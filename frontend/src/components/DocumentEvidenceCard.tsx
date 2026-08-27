import type { DocumentDetailResponse } from "../types/api";
import { ConfidenceIndicator } from "./Badges";
import { useNavigate } from "react-router-dom";

interface DocumentEvidenceCardProps {
  doc: DocumentDetailResponse;
  applicationId: string;
}

function statusIcon(status: string): string {
  if (status === "completed") return "\u2713";
  if (status === "failed") return "\u2717";
  if (status === "processing") return "\u25CB";
  return "\u2022";
}

function statusClass(status: string): string {
  if (status === "completed") return "doc-status-ok";
  if (status === "failed") return "doc-status-fail";
  return "doc-status-pending";
}

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

function extractFieldValue(
  fields: Record<string, unknown>,
  key: string
): { value: string; confidence: number } | null {
  const raw = fields[key];
  if (!raw) return null;
  if (isExtractedField(raw)) {
    if (raw.value === null || raw.value === undefined) return null;
    return { value: String(raw.value), confidence: raw.confidence };
  }
  if (typeof raw === "string" || typeof raw === "number") {
    return { value: String(raw), confidence: 0 };
  }
  return null;
}

const DISPLAY_FIELDS = [
  { key: "pan_number", label: "PAN" },
  { key: "gst_number", label: "GSTIN" },
  { key: "phone", label: "Phone" },
  { key: "email", label: "Email" },
  { key: "name", label: "Name" },
  { key: "address", label: "Address" },
  { key: "date_of_birth", label: "DOB" },
  { key: "registration_number", label: "Registration" },
];

export function DocumentEvidenceCard({ doc, applicationId }: DocumentEvidenceCardProps) {
  const navigate = useNavigate();

  return (
    <div className="doc-evidence-card">
      <div className="doc-evidence-header">
        <div className="doc-evidence-title-row">
          <span className="doc-evidence-type">
            {doc.document_type.replace(/_/g, " ")}
          </span>
          <span className={`doc-evidence-status ${statusClass(doc.processing_status)}`}>
            <span aria-hidden="true">{statusIcon(doc.processing_status)}</span>
            {doc.processing_status}
          </span>
        </div>
        <div className="doc-evidence-filename">{doc.original_filename}</div>
      </div>

      <div className="doc-evidence-confidence-grid">
        <div className="doc-confidence-item">
          <span className="doc-confidence-label">Overall</span>
          <ConfidenceIndicator value={doc.overall_confidence} />
        </div>
        <div className="doc-confidence-item">
          <span className="doc-confidence-label">OCR</span>
          <ConfidenceIndicator value={doc.ocr_confidence} />
        </div>
        <div className="doc-confidence-item">
          <span className="doc-confidence-label">Field Extraction</span>
          <ConfidenceIndicator value={doc.field_extraction_confidence} />
        </div>
      </div>

      {doc.processing_method && (
        <div className="doc-evidence-method">
          Method: <span className="mono">{doc.processing_method}</span>
        </div>
      )}

      {Object.keys(doc.extracted_fields).length > 0 && (
        <div className="doc-extracted-fields">
          <span className="doc-extracted-title">Extracted Fields</span>
          <div className="doc-extracted-grid">
            {DISPLAY_FIELDS.map(({ key, label }) => {
              const field = extractFieldValue(doc.extracted_fields, key);
              if (!field) return null;
              return (
                <div key={key} className="doc-extracted-row">
                  <span className="doc-extracted-key">{label}</span>
                  <span className="doc-extracted-value mono">{field.value}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {doc.error_code && (
        <div className="doc-evidence-error">
          <strong>{doc.error_code}</strong>
          {doc.error_message && <span> — {doc.error_message}</span>}
        </div>
      )}

      <button
        className="btn btn-secondary btn-sm doc-view-btn"
        onClick={() =>
          navigate(`/applications/${applicationId}/documents/${doc.document_id}`)
        }
      >
        View Document
      </button>
    </div>
  );
}
