import type { ApplicationSummaryResponse } from "../types/api";
import { StateBadge, DecisionBadge, RiskBadge } from "./Badges";
import { formatTimestamp } from "../utils/format";

interface ApplicationTableProps {
  applications: ApplicationSummaryResponse[];
  onSelect?: (id: string) => void;
}

export function ApplicationTable({ applications, onSelect }: ApplicationTableProps) {
  if (applications.length === 0) {
    return null;
  }

  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>Applicant</th>
            <th>Application ID</th>
            <th>State</th>
            <th>Decision</th>
            <th>Risk</th>
            <th>Created</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {applications.map((app) => (
            <tr
              key={app.application_id}
              className={onSelect ? "clickable" : undefined}
              onClick={onSelect ? () => onSelect(app.application_id) : undefined}
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
              <td>
                <span className="app-table-id-mono" title={app.application_id}>
                  {app.application_id.slice(0, 8)}...
                </span>
              </td>
              <td><StateBadge state={app.current_state} /></td>
              <td><DecisionBadge decision={app.final_decision} /></td>
              <td><RiskBadge risk={app.risk_level} /></td>
              <td>{formatTimestamp(app.created_at)}</td>
              <td>{formatTimestamp(app.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
