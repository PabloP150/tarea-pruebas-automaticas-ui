import type { Status } from "../types";

interface Props {
  status: Status;
}

const LABEL_MAP: Record<Status, string> = {
  OPEN:      "OPEN",
  ACK:       "ACK",
  ESCALATED: "ESCALATED",
  RESOLVED:  "RESOLVED",
};

/**
 * StatusChip — uses CSS class-based tokens instead of inline rgba() literals
 * (REC-03). Each status maps to a .status-chip-* class defined in styles.css
 * so the design system owns the color values, not the component.
 */
export default function StatusChip({ status }: Props) {
  return (
    <span
      className={`status-chip status-chip-${status.toLowerCase()}`}
      role="status"
      aria-label={`Estado: ${LABEL_MAP[status]}`}
    >
      {LABEL_MAP[status]}
    </span>
  );
}
