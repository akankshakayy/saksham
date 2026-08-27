import type { ApplicationStatusResponse, DocumentDetailResponse } from "../types/api";

interface VerificationComparisonProps {
  app: ApplicationStatusResponse;
  docs: DocumentDetailResponse[];
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

function getDocValue(
  docs: DocumentDetailResponse[],
  fieldKey: string
): { value: string; confidence: number } | null {
  for (const doc of docs) {
    const raw = doc.extracted_fields[fieldKey];
    if (!raw) continue;
    if (isExtractedField(raw)) {
      if (raw.value !== null && raw.value !== undefined) {
        return { value: String(raw.value), confidence: raw.confidence };
      }
    } else if (typeof raw === "string" || typeof raw === "number") {
      return { value: String(raw), confidence: 0 };
    }
  }
  return null;
}

function normalize(v: string | null): string {
  if (!v) return "";
  return v.trim().toUpperCase().replace(/\s+/g, " ");
}

type MatchResult = "match" | "mismatch" | "app_only" | "doc_only" | "missing";

function compareField(
  appVal: string | null,
  docVal: { value: string; confidence: number } | null
): { result: MatchResult; docValue: string | null } {
  const av = normalize(appVal);
  const dv = docVal ? normalize(docVal.value) : null;

  if (!av && !dv) return { result: "missing", docValue: null };
  if (av && !dv) return { result: "app_only", docValue: null };
  if (!av && dv) return { result: "doc_only", docValue: dv };
  if (av === dv) return { result: "match", docValue: dv };
  return { result: "mismatch", docValue: dv };
}

const COMPARISON_FIELDS = [
  { key: "pan_number", label: "PAN Number", appKey: "pan_number" as const },
  { key: "gst_number", label: "GST Number", appKey: "gst_number" as const },
  { key: "phone", label: "Phone", appKey: "phone" as const },
  { key: "email", label: "Email", appKey: "email" as const },
  { key: "name", label: "Applicant Name", appKey: "applicant_name" as const },
  { key: "address", label: "Address", appKey: "address" as const },
];

function resultIcon(result: MatchResult): string {
  switch (result) {
    case "match": return "\u2713";
    case "mismatch": return "\u2717";
    case "app_only": return "\u2014";
    case "doc_only": return "\u2191";
    case "missing": return "\u2014";
  }
}

function resultLabel(result: MatchResult): string {
  switch (result) {
    case "match": return "Match";
    case "mismatch": return "Mismatch";
    case "app_only": return "App only";
    case "doc_only": return "Doc only";
    case "missing": return "Missing";
  }
}

function resultClass(result: MatchResult): string {
  switch (result) {
    case "match": return "vc-match";
    case "mismatch": return "vc-mismatch";
    case "app_only": return "vc-partial";
    case "doc_only": return "vc-partial";
    case "missing": return "vc-missing";
  }
}

export function VerificationComparison({ app, docs }: VerificationComparisonProps) {
  const hasDocs = docs.length > 0;
  const hasAppData = COMPARISON_FIELDS.some(
    (f) => app[f.appKey] !== null && app[f.appKey] !== undefined
  );

  if (!hasAppData && !hasDocs) {
    return (
      <div className="vc-empty">
        Insufficient data for comparison. Submit application data and upload documents to enable verification.
      </div>
    );
  }

  const rows = COMPARISON_FIELDS.map((field) => {
    const appVal = app[field.appKey];
    const docVal = getDocValue(docs, field.key);
    const { result, docValue } = compareField(appVal, docVal);

    return {
      label: field.label,
      appValue: appVal || null,
      docValue,
      result,
    };
  }).filter(
    (row) => row.result !== "missing" || row.appValue !== null
  );

  if (rows.length === 0) {
    return (
      <div className="vc-empty">
        No comparable fields found.
      </div>
    );
  }

  const matchCount = rows.filter((r) => r.result === "match").length;
  const mismatchCount = rows.filter((r) => r.result === "mismatch").length;

  return (
    <div className="verification-comparison">
      <div className="vc-summary">
        <span className="vc-match-count">{matchCount} matched</span>
        {mismatchCount > 0 && (
          <span className="vc-mismatch-count">{mismatchCount} mismatched</span>
        )}
        <span className="vc-total">{rows.length} fields compared</span>
      </div>
      <div className="table-container">
        <table className="vc-table">
          <thead>
            <tr>
              <th>Field</th>
              <th>Application</th>
              <th>Document</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <td className="vc-field-label">{row.label}</td>
                <td className="mono">{row.appValue || "\u2014"}</td>
                <td className="mono">{row.docValue || "\u2014"}</td>
                <td className={resultClass(row.result)}>
                  <span className="vc-result-icon" aria-hidden="true">
                    {resultIcon(row.result)}
                  </span>
                  {resultLabel(row.result)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
