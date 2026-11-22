import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type ResultsOut } from "../api/client";

/** The event's results, refreshed every few seconds while the app is in view. */
export function useResults(code: string, onAuthLost: () => void, everyMs = 4000) {
  const [data, setData] = useState<ResultsOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setData(await api.results(code));
      setError(null);
    } catch (err) {
      if ((err as { status?: number }).status === 401) onAuthLost();
      else setError(errorMessage(err));
    }
  }, [code, onAuthLost]);
  useEffect(() => {
    const first = setTimeout(() => void load(), 0);
    const id = setInterval(() => document.visibilityState === "visible" && void load(), everyMs);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [load, everyMs]);
  return { data, error, reload: load };
}
