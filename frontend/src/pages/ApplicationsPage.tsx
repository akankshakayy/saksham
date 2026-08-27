import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { listApplications } from "../services/api";
import { ApplicationTable } from "../components/ApplicationTable";
import { LoadingState, ErrorState, EmptyState } from "../components/Badges";
import type {
  ApplicationSummaryResponse,
  WorkflowState,
  RiskLevel,
  FinalDecision,
} from "../types/api";
import "../styles/pages.css";

const WORKFLOW_STATES: WorkflowState[] = [
  "RECEIVED", "VALIDATING", "MISSING_INFORMATION", "MORE_INFORMATION_REQUIRED",
  "VERIFYING", "ANALYZING_RISK", "DECIDING", "APPROVED", "ESCALATED",
  "REJECTED", "FAILED", "TOOL_RETRYING", "LOW_CONFIDENCE", "TOOL_FAILED",
  "ESCALATED_TO_HUMAN",
];

const RISK_LEVELS: RiskLevel[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const DECISIONS: FinalDecision[] = [
  "APPROVE", "REQUEST_MORE_INFORMATION", "ESCALATE_TO_HUMAN", "REJECT_OR_BLOCK",
];

const PAGE_SIZE = 20;

export function ApplicationsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const mountedRef = useRef(true);

  const [search, setSearch] = useState(searchParams.get("q") || "");
  const [debouncedSearch, setDebouncedSearch] = useState(searchParams.get("q") || "");
  const [stateFilter, setStateFilter] = useState(searchParams.get("state") || "");
  const [riskFilter, setRiskFilter] = useState(searchParams.get("risk") || "");
  const [decisionFilter, setDecisionFilter] = useState(searchParams.get("decision") || "");
  const [page, setPage] = useState(Math.max(0, parseInt(searchParams.get("page") || "0", 10)));

  const [apps, setApps] = useState<ApplicationSummaryResponse[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const updateParams = useCallback(
    (overrides: Record<string, string>) => {
      const next = new URLSearchParams(searchParams);
      for (const [k, v] of Object.entries(overrides)) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const handleSearchChange = (value: string) => {
    setSearch(value);
    setPage(0);
    updateParams({ q: value, page: "0" });
  };

  const handleFilterChange = (key: string, value: string) => {
    if (key === "state") setStateFilter(value);
    if (key === "risk") setRiskFilter(value);
    if (key === "decision") setDecisionFilter(value);
    setPage(0);
    updateParams({ [key]: value, page: "0" });
  };

  const clearFilters = () => {
    setSearch("");
    setDebouncedSearch("");
    setStateFilter("");
    setRiskFilter("");
    setDecisionFilter("");
    setPage(0);
    setSearchParams({}, { replace: true });
  };

  const hasFilters = stateFilter || riskFilter || decisionFilter || search;

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);

      try {
        const result = await listApplications({
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
          state: stateFilter || undefined,
          risk_level: riskFilter || undefined,
          final_decision: decisionFilter || undefined,
          q: debouncedSearch || undefined,
        });

        if (cancelled) return;
        setApps(result.applications);
        setTotalCount(result.total);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load applications");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [page, stateFilter, riskFilter, decisionFilter, debouncedSearch]);

  const handleRetry = () => {
    setError(null);
    setLoading(true);
  };

  return (
    <>
      <div className="page-header">
        <h1>Applications</h1>
        <p>All onboarding applications</p>
      </div>
      <div className="page-body">
        <div className="filter-bar">
          <div className="search-input-wrapper">
            <input
              type="text"
              className="form-input search-input"
              placeholder="Search by name or ID..."
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              aria-label="Search applications"
            />
          </div>
          <label>
            <span className="form-label" style={{ marginBottom: 0 }}>State</span>
            <select
              className="form-input form-select"
              value={stateFilter}
              onChange={(e) => handleFilterChange("state", e.target.value)}
            >
              <option value="">All states</option>
              {WORKFLOW_STATES.map((s) => (
                <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="form-label" style={{ marginBottom: 0 }}>Risk</span>
            <select
              className="form-input form-select"
              value={riskFilter}
              onChange={(e) => handleFilterChange("risk", e.target.value)}
            >
              <option value="">All risk levels</option>
              {RISK_LEVELS.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="form-label" style={{ marginBottom: 0 }}>Decision</span>
            <select
              className="form-input form-select"
              value={decisionFilter}
              onChange={(e) => handleFilterChange("decision", e.target.value)}
            >
              <option value="">All decisions</option>
              {DECISIONS.map((d) => (
                <option key={d} value={d}>{d.replace(/_/g, " ")}</option>
              ))}
            </select>
          </label>
          {hasFilters && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={clearFilters}
              style={{ alignSelf: "flex-end" }}
            >
              Clear filters
            </button>
          )}
        </div>

        {loading && <LoadingState message="Loading applications..." />}
        {error && <ErrorState message={error} onRetry={handleRetry} />}

        {!loading && !error && (
          <>
            {totalCount === 0 && !hasFilters ? (
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
            ) : apps.length === 0 && hasFilters ? (
              <EmptyState
                title="No applications found"
                description="Try adjusting your search or filters."
                action={
                  <button className="btn btn-secondary" onClick={clearFilters}>
                    Clear filters
                  </button>
                }
              />
            ) : (
              <>
                <ApplicationTable
                  applications={apps}
                  onSelect={(id) => navigate(`/applications/${id}`)}
                />
                <div className="pagination">
                  <span>
                    {debouncedSearch
                      ? `${apps.length} of ${totalCount} matching`
                      : `Showing ${page * PAGE_SIZE + 1}\u2013${Math.min((page + 1) * PAGE_SIZE, totalCount)} of ${totalCount}`}
                  </span>
                  <div className="pagination-controls">
                    <button
                      className="btn btn-secondary btn-sm"
                      disabled={page === 0}
                      onClick={() => {
                        const p = page - 1;
                        setPage(p);
                        updateParams({ page: String(p) });
                      }}
                    >
                      Previous
                    </button>
                    <span className="pagination-info">
                      Page {page + 1} of {totalPages}
                    </span>
                    <button
                      className="btn btn-secondary btn-sm"
                      disabled={page >= totalPages - 1}
                      onClick={() => {
                        const p = page + 1;
                        setPage(p);
                        updateParams({ page: String(p) });
                      }}
                    >
                      Next
                    </button>
                  </div>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </>
  );
}
