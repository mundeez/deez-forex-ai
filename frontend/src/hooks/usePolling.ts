import { useEffect, useRef, useCallback } from "react";

/**
 * Polling hook with automatic AbortController cleanup.
 *
 * The fetcher receives an AbortSignal and MUST pass it to fetch():
 *   usePolling(async (signal) => {
 *     const res = await fetch(url, { signal });
 *     ...
 *   }, 15000, [symbol]);
 *
 * On unmount or dependency change:
 *   - The interval is cleared
 *   - Any in-flight request is aborted (no NS_BINDING_ABORTED)
 */
export function usePolling(
  fetcher: (signal: AbortSignal) => Promise<void>,
  intervalMs: number,
  deps: any[] = []
) {
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    const controller = new AbortController();

    const poll = () => {
      fetcherRef.current(controller.signal).catch((e) => {
        if (e?.name !== "AbortError") throw e;
      });
    };

    poll(); // immediate first fetch
    const interval = setInterval(poll, intervalMs);

    return () => {
      clearInterval(interval);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/**
 * One-time fetch hook with AbortController cleanup.
 *
 *   useFetchOnce(async (signal) => {
 *     const res = await fetch(url, { signal });
 *     ...
 *   }, [symbol]);
 */
export function useFetchOnce(
  fetcher: (signal: AbortSignal) => Promise<void>,
  deps: any[] = []
) {
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    const controller = new AbortController();
    fetcherRef.current(controller.signal).catch((e) => {
      if (e?.name !== "AbortError") throw e;
    });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/**
 * Helper: safely fetch with an AbortSignal, returning parsed JSON or null.
 * AbortError is silently swallowed; other errors are logged.
 */
export async function fetchJSON<T = any>(
  url: string,
  signal?: AbortSignal,
  options?: RequestInit
): Promise<T | null> {
  try {
    const res = await fetch(url, { ...options, signal });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch (e: any) {
    if (e?.name === "AbortError") return null;
    console.error("fetch error:", url, e);
    return null;
  }
}
