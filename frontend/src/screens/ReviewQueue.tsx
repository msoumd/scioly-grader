import { useCallback, useEffect, useState } from "react";
import {
  api,
  errorMessage,
  type DuplicateOut,
  type EventOut,
  type ScanSummary,
} from "../api/client";
import { reasonChips } from "../lib/flags";
import { href } from "../lib/route";
import { preloadScan } from "../lib/data";

const POLL_MS = 3000;

function ago(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function ReviewQueue({ event, onAuthLost }: { event: EventOut; onAuthLost: () => void }) {
  const [scans, setScans] = useState<ScanSummary[] | null>(null);
  const [dupes, setDupes] = useState<DuplicateOut[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, d] = await Promise.all([
        api.scans(event.code, "needs_review"),
        api.duplicates(event.code),
      ]);
      setScans(list); // oldest first
      setDupes(d);
      setError(null);
      if (list[0]) preloadScan(list[0].id);
    } catch (err) {
      if ((err as { status?: number }).status === 401) onAuthLost();
      else setError(errorMessage(err));
    }
  }, [event.code, onAuthLost]);

  useEffect(() => {
    const first = setTimeout(() => void load(), 0);
    const id = setInterval(() => document.visibilityState === "visible" && void load(), POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [load]);

  return (
    <>
      <h1 className="section-title" style={{ marginTop: 4 }}>
        Needs review <small>{scans ? `${scans.length} waiting` : ""}</small>
      </h1>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {dupes.length > 0 && (
        <p className="alert alert--info">
          {dupes.length === 1
            ? `Team ${dupes[0]!.team_number} has more than one sheet.`
            : `${dupes.length} teams have more than one sheet.`}{" "}
          <a href={href({ tab: "duplicates" })}>Compare and choose</a>
        </p>
      )}
      <ul className="rows" aria-label="Sheets to review">
        {scans === null && <li className="empty">Loading…</li>}
        {scans?.length === 0 && (
          <li className="empty">Nothing to review. Every sheet so far was read cleanly.</li>
        )}
        {scans?.map((s) => (
          <li key={s.id}>
            <a className="row" href={href({ tab: "review", scanId: s.id })}>
              <span className="bubble bubble--needs_review" aria-hidden />
              <div className="row__main">
                <strong>{s.team_number != null ? `Team ${s.team_number}` : "Team not read"}</strong>
                <div className="chips">
                  {reasonChips(s.flags).map((c) => (
                    <span key={c} className="chip">
                      {c}
                    </span>
                  ))}
                </div>
              </div>
              <span className="hint">{ago(s.updated_at)}</span>
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}
