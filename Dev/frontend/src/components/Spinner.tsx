import type { CSSProperties } from "react";

/**
 * Spinner — reusable loading indicator (REC-04).
 * Replaces the repeated inline <span className="spinner" style={{...}} />
 * pattern scattered across Dashboard. Callers control size via the `size`
 * prop; the base .spinner class (styles.css) owns colors and animation.
 */

interface Props {
  /** px size — defaults to 14 (matches the base .spinner rule in styles.css) */
  size?: number;
  /** Additional CSS class names */
  className?: string;
}

export default function Spinner({ size = 14, className = "" }: Props) {
  const style: CSSProperties | undefined =
    size !== 14 ? { width: `${size}px`, height: `${size}px` } : undefined;

  return (
    <span
      className={`spinner${className ? ` ${className}` : ""}`}
      style={style}
      aria-hidden="true"
    />
  );
}
