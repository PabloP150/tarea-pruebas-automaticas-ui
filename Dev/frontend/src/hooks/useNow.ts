import { useContext } from "react";
import { NowContext } from "../providers/NowProvider";

/**
 * Returns the current timestamp (ms) from the global ticker.
 * Use this instead of Date.now() inside render to avoid per-component
 * setInterval proliferation (RF-03).
 */
export function useNow(): number {
  return useContext(NowContext);
}
