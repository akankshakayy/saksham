import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { createApplication, uploadDocument } from "../services/api";
import { ApiError } from "../services/api";
import type { SubmitApplicationRequest, DocumentUploadResponse, WorkflowState } from "../types/api";
import { formatState } from "../utils/format";
import "../styles/pages.css";

const PAN_REGEX = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const GST_REGEX = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;
const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ALLOWED_MIME_TYPES = ["image/jpeg", "image/png", "application/pdf"];

type PageFlow = "form" | "documents" | "submitting" | "success" | "partial_failure";

interface FormData {
  applicant_name: string;
  business_name: string;
  business_type: string;
  pan_number: string;
  gst_number: string;
  address: string;
  phone: string;
  email: string;
}

interface FieldErrors {
  [key: string]: string;
}

interface PendingDocument {
  id: string;
  document_type: string;
  file: File;
  status: "ready" | "uploading" | "processed" | "failed";
  result?: DocumentUploadResponse;
  error?: string;
}

const DOCUMENT_TYPES = [
  { value: "PAN_CARD", label: "PAN Card" },
  { value: "GST_CERTIFICATE", label: "GST Certificate" },
  { value: "AADHAAR_CARD", label: "Aadhaar Card" },
  { value: "BUSINESS_REGISTRATION", label: "Business Registration" },
];

export function NewApplicationPage() {
  const navigate = useNavigate();
  const [flow, setFlow] = useState<PageFlow>("form");
  const [form, setForm] = useState<FormData>({
    applicant_name: "",
    business_name: "",
    business_type: "",
    pan_number: "",
    gst_number: "",
    address: "",
    phone: "",
    email: "",
  });
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [pendingDocs, setPendingDocs] = useState<PendingDocument[]>([]);
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [applicationState, setApplicationState] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const docTypeSelectRef = useRef<HTMLSelectElement>(null);

  const validateForm = useCallback((): boolean => {
    const errors: FieldErrors = {};

    if (!form.applicant_name.trim()) {
      errors.applicant_name = "Applicant name is required";
    }
    if (!form.business_name.trim()) {
      errors.business_name = "Business name is required";
    }
    if (!form.pan_number.trim()) {
      errors.pan_number = "PAN number is required";
    } else if (!PAN_REGEX.test(form.pan_number.trim().toUpperCase())) {
      errors.pan_number = "Invalid PAN format (e.g. ABCDE1234F)";
    }
    if (!form.phone.trim()) {
      errors.phone = "Phone number is required";
    } else if (!/^[0-9]{10}$/.test(form.phone.trim())) {
      errors.phone = "Phone must be 10 digits";
    }
    if (form.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
      errors.email = "Invalid email format";
    }
    if (form.gst_number.trim() && !GST_REGEX.test(form.gst_number.trim().toUpperCase())) {
      errors.gst_number = "Invalid GST format";
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }, [form]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    if (fieldErrors[name]) {
      setFieldErrors((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (validateForm()) {
      setFlow("documents");
    }
  };

  const validateFile = (file: File): string | null => {
    if (!ALLOWED_MIME_TYPES.includes(file.type)) {
      return "Only JPEG, PNG, and PDF files are allowed";
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File must be under ${Math.round(MAX_FILE_SIZE / (1024 * 1024))}MB`;
    }
    return null;
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !docTypeSelectRef.current?.value) return;

    const error = validateFile(file);
    if (error) {
      setSubmitError(error);
      return;
    }

    const docType = docTypeSelectRef.current.value;
    const newDoc: PendingDocument = {
      id: `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      document_type: docType,
      file,
      status: "ready",
    };

    setPendingDocs((prev) => [...prev, newDoc]);
    setSubmitError(null);
    e.target.value = "";
  };

  const handleRemoveDoc = (docId: string) => {
    setPendingDocs((prev) => prev.filter((d) => d.id !== docId));
  };

  const handleSubmitAll = async () => {
    setFlow("submitting");
    setSubmitError(null);

    try {
      const payload: SubmitApplicationRequest = {
        applicant_name: form.applicant_name.trim() || null,
        business_name: form.business_name.trim() || null,
        business_type: form.business_type.trim() || null,
        pan_number: form.pan_number.trim().toUpperCase() || null,
        gst_number: form.gst_number.trim().toUpperCase() || null,
        address: form.address.trim() || null,
        phone: form.phone.trim() || null,
        email: form.email.trim() || null,
      };

      const appResult = await createApplication(payload);
      setApplicationId(appResult.application_id);
      setApplicationState(appResult.state);

      if (pendingDocs.length === 0) {
        setFlow("success");
        return;
      }

      const docResults: PendingDocument[] = [];

      for (const doc of pendingDocs) {
        setPendingDocs((prev) =>
          prev.map((d) => (d.id === doc.id ? { ...d, status: "uploading" as const } : d))
        );

        try {
          const result = await uploadDocument(
            appResult.application_id,
            doc.file,
            doc.document_type
          );
          docResults.push({ ...doc, status: "processed", result });
        } catch (err) {
          const errorMsg =
            err instanceof ApiError ? err.message : "Upload failed";
          docResults.push({ ...doc, status: "failed", error: errorMsg });
        }

        setPendingDocs((prev) =>
          prev.map((d) => {
            const r = docResults.find((cr) => cr.id === d.id);
            return r || d;
          })
        );
      }

      setPendingDocs(docResults);

      const allFailed = docResults.every((d) => d.status === "failed");
      const someFailed = docResults.some((d) => d.status === "failed");

      if (allFailed) {
        setSubmitError("All document uploads failed. You can retry or continue without documents.");
        setFlow("partial_failure");
      } else if (someFailed) {
        setFlow("partial_failure");
      } else {
        setFlow("success");
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmitError(err.message);
      } else {
        setSubmitError("An unexpected error occurred. Please try again.");
      }
      setFlow("form");
    }
  };

  const handleRetryFailed = async () => {
    if (!applicationId) return;

    const failedDocs = pendingDocs.filter((d) => d.status === "failed");
    const updatedDocs = [...pendingDocs];

    for (const doc of failedDocs) {
      setPendingDocs((prev) =>
        prev.map((d) => (d.id === doc.id ? { ...d, status: "uploading" as const, error: undefined } : d))
      );

      try {
        const result = await uploadDocument(applicationId, doc.file, doc.document_type);
        const idx = updatedDocs.findIndex((d) => d.id === doc.id);
        if (idx >= 0) {
          updatedDocs[idx] = { ...doc, status: "processed", result, error: undefined };
        }
      } catch (err) {
        const errorMsg = err instanceof ApiError ? err.message : "Upload failed";
        const idx = updatedDocs.findIndex((d) => d.id === doc.id);
        if (idx >= 0) {
          updatedDocs[idx] = { ...doc, status: "failed", error: errorMsg };
        }
      }

      setPendingDocs([...updatedDocs]);
    }

    const stillFailed = updatedDocs.filter((d) => d.status === "failed");
    if (stillFailed.length === 0) {
      setFlow("success");
    }
  };

  const handleContinueWithoutDocs = () => {
    setFlow("success");
  };

  const formatDocType = (type: string) => {
    return DOCUMENT_TYPES.find((dt) => dt.value === type)?.label || type;
  };

  const getAcceptedTypes = () => ALLOWED_MIME_TYPES.join(",");

  if (flow === "form") {
    return (
      <>
        <div className="page-header">
          <h1>New Application</h1>
          <p>Submit a new onboarding application</p>
        </div>
        <div className="page-body">
          <div className="card" style={{ maxWidth: 700 }}>
            <form onSubmit={handleFormSubmit}>
              <div className="detail-section">
                <div className="detail-section-title">Applicant Information</div>
                <div className="detail-grid">
                  <div className="form-group">
                    <label className="form-label required" htmlFor="applicant_name">
                      Applicant Name
                    </label>
                    <input
                      id="applicant_name"
                      name="applicant_name"
                      className={`form-input ${fieldErrors.applicant_name ? "form-input-error" : ""}`}
                      value={form.applicant_name}
                      onChange={handleChange}
                      placeholder="e.g. John Doe"
                    />
                    {fieldErrors.applicant_name && (
                      <span className="form-error">{fieldErrors.applicant_name}</span>
                    )}
                  </div>
                  <div className="form-group">
                    <label className="form-label required" htmlFor="business_name">
                      Business Name
                    </label>
                    <input
                      id="business_name"
                      name="business_name"
                      className={`form-input ${fieldErrors.business_name ? "form-input-error" : ""}`}
                      value={form.business_name}
                      onChange={handleChange}
                      placeholder="e.g. Acme Corp"
                    />
                    {fieldErrors.business_name && (
                      <span className="form-error">{fieldErrors.business_name}</span>
                    )}
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor="business_type">
                      Business Type
                    </label>
                    <input
                      id="business_type"
                      name="business_type"
                      className="form-input"
                      value={form.business_type}
                      onChange={handleChange}
                      placeholder="e.g. Private Limited"
                    />
                  </div>
                </div>
              </div>

              <div className="detail-section">
                <div className="detail-section-title">Identity & Tax</div>
                <div className="detail-grid">
                  <div className="form-group">
                    <label className="form-label required" htmlFor="pan_number">
                      PAN Number
                    </label>
                    <input
                      id="pan_number"
                      name="pan_number"
                      className={`form-input ${fieldErrors.pan_number ? "form-input-error" : ""}`}
                      value={form.pan_number}
                      onChange={handleChange}
                      placeholder="e.g. ABCDE1234F"
                      style={{ fontFamily: "var(--font-mono)" }}
                      maxLength={10}
                    />
                    {fieldErrors.pan_number && (
                      <span className="form-error">{fieldErrors.pan_number}</span>
                    )}
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor="gst_number">
                      GST Number
                    </label>
                    <input
                      id="gst_number"
                      name="gst_number"
                      className={`form-input ${fieldErrors.gst_number ? "form-input-error" : ""}`}
                      value={form.gst_number}
                      onChange={handleChange}
                      placeholder="e.g. 27AABCT1234D1Z5"
                      style={{ fontFamily: "var(--font-mono)" }}
                      maxLength={15}
                    />
                    {fieldErrors.gst_number && (
                      <span className="form-error">{fieldErrors.gst_number}</span>
                    )}
                  </div>
                </div>
              </div>

              <div className="detail-section">
                <div className="detail-section-title">Contact</div>
                <div className="detail-grid">
                  <div className="form-group">
                    <label className="form-label required" htmlFor="phone">
                      Phone
                    </label>
                    <input
                      id="phone"
                      name="phone"
                      className={`form-input ${fieldErrors.phone ? "form-input-error" : ""}`}
                      value={form.phone}
                      onChange={handleChange}
                      placeholder="e.g. 9876543210"
                      maxLength={10}
                    />
                    {fieldErrors.phone && (
                      <span className="form-error">{fieldErrors.phone}</span>
                    )}
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor="email">
                      Email
                    </label>
                    <input
                      id="email"
                      name="email"
                      className={`form-input ${fieldErrors.email ? "form-input-error" : ""}`}
                      type="email"
                      value={form.email}
                      onChange={handleChange}
                      placeholder="e.g. john@example.com"
                    />
                    {fieldErrors.email && (
                      <span className="form-error">{fieldErrors.email}</span>
                    )}
                  </div>
                  <div className="form-group" style={{ gridColumn: "1 / -1" }}>
                    <label className="form-label" htmlFor="address">
                      Address
                    </label>
                    <input
                      id="address"
                      name="address"
                      className="form-input"
                      value={form.address}
                      onChange={handleChange}
                      placeholder="e.g. 123 Main St, Mumbai"
                    />
                  </div>
                </div>
              </div>

              {submitError && (
                <div className="form-error-banner" role="alert">
                  {submitError}
                </div>
              )}

              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button type="submit" className="btn btn-primary">
                  Continue to Documents
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => navigate("/applications")}
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      </>
    );
  }

  if (flow === "documents") {
    const readyDocs = pendingDocs.filter((d) => d.status === "ready");

    return (
      <>
        <div className="page-header">
          <h1>New Application</h1>
          <p>Upload supporting documents (optional)</p>
        </div>
        <div className="page-body">
          <div className="card" style={{ maxWidth: 700 }}>
            <div className="detail-section">
              <div className="detail-section-title">Documents</div>
              <p className="form-hint" style={{ marginBottom: 16 }}>
                Accepted: JPEG, PNG, PDF. Max 10MB per file.
              </p>

              {pendingDocs.length > 0 && (
                <div className="doc-pending-list">
                  {pendingDocs.map((doc) => (
                    <div key={doc.id} className="doc-pending-card">
                      <div className="doc-pending-info">
                        <span className="doc-pending-type">{formatDocType(doc.document_type)}</span>
                        <span className="doc-pending-filename">{doc.file.name}</span>
                        <span className="doc-pending-size">
                          {(doc.file.size / 1024).toFixed(0)}KB
                        </span>
                      </div>
                      <button
                        type="button"
                        className="btn btn-sm btn-secondary"
                        onClick={() => handleRemoveDoc(doc.id)}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="doc-upload-row">
                <select
                  ref={docTypeSelectRef}
                  className="form-select"
                  defaultValue="PAN_CARD"
                  style={{ width: 200 }}
                >
                  {DOCUMENT_TYPES.map((dt) => (
                    <option key={dt.value} value={dt.value}>
                      {dt.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => fileInputRef.current?.click()}
                >
                  Select File
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={getAcceptedTypes()}
                  onChange={handleFileSelect}
                  style={{ display: "none" }}
                />
              </div>

              {submitError && (
                <div className="form-error-banner" role="alert" style={{ marginTop: 12 }}>
                  {submitError}
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleSubmitAll}
              >
                Submit Application
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setFlow("form")}
              >
                Back to Form
              </button>
              {readyDocs.length === 0 && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setPendingDocs([]);
                    handleSubmitAll();
                  }}
                >
                  Skip Documents
                </button>
              )}
            </div>
          </div>
        </div>
      </>
    );
  }

  if (flow === "submitting") {
    const processedCount = pendingDocs.filter((d) => d.status === "processed").length;
    const failedCount = pendingDocs.filter((d) => d.status === "failed").length;
    const totalDocs = pendingDocs.length;

    return (
      <>
        <div className="page-header">
          <h1>New Application</h1>
          <p>Processing your application...</p>
        </div>
        <div className="page-body">
          <div className="card" style={{ maxWidth: 700 }}>
            <div className="loading-container">
              <div className="spinner" />
              <span>
                {applicationId
                  ? `Uploading documents... ${processedCount + failedCount}/${totalDocs}`
                  : "Creating application..."}
              </span>
            </div>

            {totalDocs > 0 && (
              <div className="doc-progress-list">
                {pendingDocs.map((doc) => (
                  <div key={doc.id} className="doc-progress-item">
                    <span className="doc-progress-type">{formatDocType(doc.document_type)}</span>
                    <span className="doc-progress-filename">{doc.file.name}</span>
                    <span className={`doc-progress-status status-${doc.status}`}>
                      {doc.status === "ready" && "Waiting..."}
                      {doc.status === "uploading" && "Uploading..."}
                      {doc.status === "processed" && "Done"}
                      {doc.status === "failed" && "Failed"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </>
    );
  }

  if (flow === "partial_failure") {
    const failedDocs = pendingDocs.filter((d) => d.status === "failed");
    const succeededDocs = pendingDocs.filter((d) => d.status === "processed");

    return (
      <>
        <div className="page-header">
          <h1>Partial Failure</h1>
          <p>Some documents could not be processed</p>
        </div>
        <div className="page-body">
          <div className="card" style={{ maxWidth: 700 }}>
            {applicationId && (
              <div className="success-app-id">
                Application ID: <code>{applicationId}</code>
              </div>
            )}

            {succeededDocs.length > 0 && (
              <div className="detail-section">
                <div className="detail-section-title success-text">
                  Successfully Uploaded ({succeededDocs.length})
                </div>
                <div className="doc-result-list">
                  {succeededDocs.map((doc) => (
                    <div key={doc.id} className="doc-result-card doc-result-success">
                      <div className="doc-result-info">
                        <span className="doc-result-type">{formatDocType(doc.document_type)}</span>
                        <span className="doc-result-filename">{doc.file.name}</span>
                      </div>
                      {doc.result && (
                        <div className="doc-result-confidence">
                          Confidence: {Math.round(doc.result.overall_confidence * 100)}%
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="detail-section">
              <div className="detail-section-title danger-text">
                Failed ({failedDocs.length})
              </div>
              <div className="doc-result-list">
                {failedDocs.map((doc) => (
                  <div key={doc.id} className="doc-result-card doc-result-failed">
                    <div className="doc-result-info">
                      <span className="doc-result-type">{formatDocType(doc.document_type)}</span>
                      <span className="doc-result-filename">{doc.file.name}</span>
                    </div>
                    {doc.error && <div className="doc-result-error">{doc.error}</div>}
                  </div>
                ))}
              </div>
            </div>

            {submitError && (
              <div className="form-error-banner" role="alert">
                {submitError}
              </div>
            )}

            <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleRetryFailed}
              >
                Retry Failed Documents
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleContinueWithoutDocs}
              >
                Continue Without Failed Documents
              </button>
              {applicationId && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => navigate(`/applications/${applicationId}`)}
                >
                  View Application
                </button>
              )}
            </div>
          </div>
        </div>
      </>
    );
  }

  if (flow === "success") {
    const succeededDocs = pendingDocs.filter((d) => d.status === "processed");

    return (
      <>
        <div className="page-header">
          <h1>Application Submitted</h1>
          <p>Your application has been created successfully</p>
        </div>
        <div className="page-body">
          <div className="card" style={{ maxWidth: 700 }}>
            <div className="success-icon">&#10003;</div>
            <div className="success-app-id">
              Application ID: <code>{applicationId}</code>
            </div>
            <div className="success-state">
              State: <span className="badge badge-processing">{formatState(applicationState as WorkflowState)}</span>
            </div>

            {succeededDocs.length > 0 && (
              <div className="detail-section" style={{ marginTop: 24 }}>
                <div className="detail-section-title">
                  Uploaded Documents ({succeededDocs.length})
                </div>
                <div className="doc-result-list">
                  {succeededDocs.map((doc) => (
                    <div key={doc.id} className="doc-result-card doc-result-success">
                      <div className="doc-result-info">
                        <span className="doc-result-type">{formatDocType(doc.document_type)}</span>
                        <span className="doc-result-filename">{doc.file.name}</span>
                      </div>
                      {doc.result && (
                        <div className="doc-result-confidence">
                          Confidence: {Math.round(doc.result.overall_confidence * 100)}%
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: "flex", gap: 8, marginTop: 24 }}>
              {applicationId && (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => navigate(`/applications/${applicationId}`)}
                >
                  View Application
                </button>
              )}
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => navigate("/applications")}
              >
                Back to Applications
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setForm({
                    applicant_name: "",
                    business_name: "",
                    business_type: "",
                    pan_number: "",
                    gst_number: "",
                    address: "",
                    phone: "",
                    email: "",
                  });
                  setPendingDocs([]);
                  setApplicationId(null);
                  setApplicationState(null);
                  setSubmitError(null);
                  setFlow("form");
                }}
              >
                New Application
              </button>
            </div>
          </div>
        </div>
      </>
    );
  }

  return null;
}
