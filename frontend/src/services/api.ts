import type {
  ApplicationStatusResponse,
  DocumentDetailResponse,
  DocumentSummaryResponse,
  DocumentUploadResponse,
  ErrorResponse,
  HealthResponse,
  ListApplicationsResponse,
  RawTextResponse,
  SubmitApplicationRequest,
  SubmitApplicationResponse,
  WorkflowHistoryResponse,
} from "../types/api";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  status: number;
  errorCode: string;

  constructor(status: number, errorCode: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = errorCode;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${BASE_URL}${API_PREFIX}${path}`;
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (options.body && typeof options.body === "string") {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    let errorData: ErrorResponse;
    try {
      errorData = await response.json();
    } catch {
      throw new ApiError(response.status, "UNKNOWN_ERROR", response.statusText);
    }
    throw new ApiError(
      response.status,
      errorData.error_code || "UNKNOWN_ERROR",
      errorData.message || "An unexpected error occurred"
    );
  }

  return response.json() as Promise<T>;
}

export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export async function listApplications(params?: {
  state?: string;
  risk_level?: string;
  final_decision?: string;
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<ListApplicationsResponse> {
  const searchParams = new URLSearchParams();
  if (params?.state) searchParams.set("state", params.state);
  if (params?.risk_level) searchParams.set("risk_level", params.risk_level);
  if (params?.final_decision) searchParams.set("final_decision", params.final_decision);
  if (params?.q) searchParams.set("q", params.q);
  if (params?.limit !== undefined) searchParams.set("limit", String(params.limit));
  if (params?.offset !== undefined) searchParams.set("offset", String(params.offset));

  const qs = searchParams.toString();
  return request<ListApplicationsResponse>(`/applications${qs ? `?${qs}` : ""}`);
}

export async function createApplication(
  data: SubmitApplicationRequest
): Promise<SubmitApplicationResponse> {
  return request<SubmitApplicationResponse>("/applications", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function getApplication(
  applicationId: string
): Promise<ApplicationStatusResponse> {
  return request<ApplicationStatusResponse>(`/applications/${applicationId}`);
}

export async function getApplicationHistory(
  applicationId: string
): Promise<WorkflowHistoryResponse> {
  return request<WorkflowHistoryResponse>(`/applications/${applicationId}/history`);
}

export async function getApplicationDocuments(
  applicationId: string
): Promise<DocumentSummaryResponse[]> {
  return request<DocumentSummaryResponse[]>(
    `/applications/${applicationId}/documents`
  );
}

export async function getDocument(
  applicationId: string,
  documentId: string
): Promise<DocumentDetailResponse> {
  return request<DocumentDetailResponse>(
    `/applications/${applicationId}/documents/${documentId}`
  );
}

export async function getDocumentRawText(
  applicationId: string,
  documentId: string
): Promise<RawTextResponse> {
  return request<RawTextResponse>(
    `/applications/${applicationId}/documents/${documentId}/raw-text`
  );
}

export async function uploadDocument(
  applicationId: string,
  file: File,
  documentType: string
): Promise<DocumentUploadResponse> {
  const url = `${BASE_URL}${API_PREFIX}/applications/${applicationId}/documents`;
  const formData = new FormData();
  formData.append("file", file);
  formData.append("document_type", documentType);

  const response = await fetch(url, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    let errorData: ErrorResponse;
    try {
      errorData = await response.json();
    } catch {
      throw new ApiError(response.status, "UNKNOWN_ERROR", response.statusText);
    }
    throw new ApiError(
      response.status,
      errorData.error_code || "UNKNOWN_ERROR",
      errorData.message || "Upload failed"
    );
  }

  return response.json() as Promise<DocumentUploadResponse>;
}
