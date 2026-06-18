import { useNow } from "../hooks/useNow";

interface Props {
  deadline: string; // ISO-8601 UTC string
}

function formatRemaining(ms: number): string {
  if (ms <= 0) return "vencido";
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(seconds).padStart(2, "0")}s`;
  }
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function getSlaClass(ms: number): string {
  if (ms <= 0) return "sla-countdown sla-danger";
  if (ms < 900_000) return "sla-countdown sla-warn"; // < 15 min
  return "sla-countdown sla-ok";
}

function getSlaIcon(ms: number): string {
  if (ms <= 0) return "⚠";
  return "◷";
}

/**
 * SlaCountdown — derives remaining time from the global NowContext ticker
 * (RF-03, REC-06). No local setInterval; no Date.now() in render body.
 * With 50 rows on screen there is still exactly ONE interval app-wide.
 */
export default function SlaCountdown({ deadline }: Props) {
  const now = useNow();
  const remaining = new Date(deadline).getTime() - now;

  const label = formatRemaining(remaining);
  const ariaLabel = remaining <= 0 ? "SLA vencido" : `SLA restante: ${label}`;

  return (
    <span
      className={getSlaClass(remaining)}
      role="timer"
      aria-label={ariaLabel}
      aria-live="off"
    >
      <span className="sla-countdown-icon" aria-hidden="true">
        {getSlaIcon(remaining)}
      </span>
      {label}
    </span>
  );
}
