import type { Severity } from "../types";

interface Props {
  severity: Severity;
}

const LABELS: Record<Severity, string> = {
  P0: "P0 · Crítico",
  P1: "P1 · Alto",
  P2: "P2 · Normal",
};

const CLASS_MAP: Record<Severity, string> = {
  P0: "severity-badge severity-badge-p0",
  P1: "severity-badge severity-badge-p1",
  P2: "severity-badge severity-badge-p2",
};

export default function SeverityBadge({ severity }: Props) {
  return (
    <span className={CLASS_MAP[severity]} role="status" aria-label={`Severidad ${LABELS[severity]}`}>
      <span className="severity-badge-dot" aria-hidden="true" />
      {severity}
    </span>
  );
}
