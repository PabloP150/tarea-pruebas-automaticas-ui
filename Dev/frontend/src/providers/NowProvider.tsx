import { createContext, useState, useEffect, type ReactNode } from "react";

/**
 * NowContext — provides the current timestamp (ms since epoch) updated once
 * per second from a SINGLE global setInterval.
 *
 * Motivation (RF-03): with N rows in the Dashboard each mounting their own
 * SlaCountdown, the naive approach spawns N intervals. One global ticker
 * reduces that to 1 interval for the entire app tree.
 */
export const NowContext = createContext<number>(Date.now());

interface Props {
  children: ReactNode;
}

export function NowProvider({ children }: Props) {
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(id);
  }, []);

  return <NowContext.Provider value={now}>{children}</NowContext.Provider>;
}
