import { useEffect, useRef, useState } from "react";
import type { RetentionStatus } from "./api";

function formatCountdown(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

type Props = {
  retention: RetentionStatus | null;
  onExpired?: () => void;
};

export function RetentionCountdown({ retention, onExpired }: Props) {
  const [seconds, setSeconds] = useState<number | null>(null);
  const expiredCalled = useRef(false);
  const onExpiredRef = useRef(onExpired);
  onExpiredRef.current = onExpired;

  useEffect(() => {
    expiredCalled.current = false;

    if (!retention?.enabled || !retention.purge_at) {
      setSeconds(null);
      return;
    }

    const deadline = new Date(retention.purge_at).getTime();
    if (Number.isNaN(deadline)) {
      setSeconds(null);
      return;
    }

    const tick = () => {
      const remaining = Math.max(0, Math.floor((deadline - Date.now()) / 1000));
      setSeconds(remaining);
      if (remaining === 0 && !expiredCalled.current) {
        expiredCalled.current = true;
        onExpiredRef.current?.();
      }
    };

    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [retention?.enabled, retention?.purge_at]);

  if (!retention?.enabled || seconds === null || retention.purge_at === null) {
    return null;
  }

  const urgent = seconds <= 15 * 60;

  return (
    <span
      className={`retention-countdown${urgent ? " urgent" : ""}`}
      title={`Elevdata raderas automatiskt ${retention.retention_hours} timmar efter Excel-import`}
    >
      Radering om {formatCountdown(seconds)}
    </span>
  );
}
