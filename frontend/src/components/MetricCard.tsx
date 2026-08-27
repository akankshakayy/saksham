export function MetricCard({
  label,
  value,
  variant,
  subtitle,
  onClick,
}: {
  label: string;
  value: string | number;
  variant?: "default" | "success" | "warning" | "danger" | "info" | "critical";
  subtitle?: string;
  onClick?: () => void;
}) {
  const colorMap: Record<string, string> = {
    default: "var(--color-text)",
    success: "var(--color-success)",
    warning: "var(--color-warning)",
    danger: "var(--color-danger)",
    info: "var(--color-info)",
    critical: "var(--color-critical)",
  };

  return (
    <div
      className={`metric-card${onClick ? " metric-card-clickable" : ""}`}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") onClick(); } : undefined}
    >
      <div className="metric-card-label">{label}</div>
      <div className="metric-card-value" style={{ color: colorMap[variant || "default"] }}>
        {value}
      </div>
      {subtitle && <div className="metric-card-subtitle">{subtitle}</div>}
    </div>
  );
}
