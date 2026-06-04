import { useState, useEffect, useCallback, useRef } from 'react';

export function useCountdown(initialSeconds: number, onExpire?: () => void) {
  const [remaining, setRemaining] = useState(initialSeconds);
  const [active, setActive] = useState(false);
  const onExpireRef = useRef(onExpire);
  onExpireRef.current = onExpire;

  const start = useCallback(() => {
    setRemaining(initialSeconds);
    setActive(true);
  }, [initialSeconds]);

  const stop = useCallback(() => {
    setActive(false);
  }, []);

  useEffect(() => {
    if (!active) return;
    if (remaining <= 0) {
      setActive(false);
      onExpireRef.current?.();
      return;
    }
    const timer = setTimeout(() => setRemaining(r => r - 1), 1000);
    return () => clearTimeout(timer);
  }, [active, remaining]);

  return {
    remaining,
    active,
    start,
    stop,
    ratio: initialSeconds > 0 ? remaining / initialSeconds : 0,
  };
}
