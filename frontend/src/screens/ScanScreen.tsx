import { useCallback, useEffect, useState, type ChangeEvent } from "react";
import { api, errorMessage, type EventOut, type ScanStatus, type ScanSummary } from "../api/client";
import { Camera } from "../components/Camera";
import { queue } from "../lib/queue";
import type { QueueItem } from "../lib/uploadQueue";

const POLL_MS = 2000;
const SHOW_RECENT = 20;

const STATUS_TEXT: Record<ScanStatus, string> = {
  processing: "Reading…",
  confirmed: "Counted",
  needs_review: "Needs review",
  failed: "Couldn't read",
  discarded: "Discarded",
};

const QUEUE_TEXT: Record<QueueItem["state"], string> = {
  waiting: "Waiting to upload",
  uploading: "Uploading",
  paused: "Log in again to upload",
  rejected: "Not accepted",
};

function stamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function useQueue(): QueueItem[] {
  const [items, setItems] = useState<QueueItem[]>(queue.snapshot());
  useEffect(() => {
    void queue.start();
    return queue.subscribe(setItems);
  }, []);
  return items;
}

function useRecentScans(eventCode: string, onAuthLost: () => void) {
  const [scans, setScans] = useState<ScanSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const all = await api.scans(eventCode);
      setScans(all.slice(-SHOW_RECENT).reverse());
      setError(null);
    } catch (err) {
      if ((err as { status?: number }).status === 401) onAuthLost();
      else setError(errorMessage(err));
    }
  }, [eventCode, onAuthLost]);

  useEffect(() => {
    const first = setTimeout(() => void load(), 0);
    const id = setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_MS);
    const off = queue.onUploaded(() => void load());
    return () => {
      clearTimeout(first);
      clearInterval(id);
      off();
    };
  }, [load]);

  return { scans, error };
}

export function ScanScreen({ event, onAuthLost }: { event: EventOut; onAuthLost: () => void }) {
  const items = useQueue();
  const { scans, error } = useRecentScans(event.code, onAuthLost);
  const pending = items.filter((i) => i.eventCode === event.code || i.state !== "rejected");

  const onCapture = useCallback(
    (photo: Blob) => void queue.add(event.code, photo, `camera-${stamp()}.jpg`),
    [event.code],
  );

  function onFiles(e: ChangeEvent<HTMLInputElement>) {
    for (const file of Array.from(e.target.files ?? [])) {
      void queue.add(event.code, file, file.name || `upload-${stamp()}`);
    }
    e.target.value = ""; // allow picking the same file again
  }

  return (
    <>
      <Camera onCapture={onCapture} />

      <div style={{ marginTop: 14 }}>
        <label className="upload-label">
          <input
            type="file"
            accept="image/*,.heic,.heif,application/pdf,.pdf"
            multiple
            onChange={onFiles}
            aria-label="Upload photos or PDF"
          />
          <span className="btn btn--quiet" aria-hidden>
            Upload photos or PDF
          </span>
        </label>
      </div>

      {pending.length > 0 && (
        <>
          <h2 className="section-title">
            Sending <small>{pending.length} left</small>
          </h2>
          <ul className="rows" aria-label="Uploads waiting">
            {pending.map((i) => (
              <li className="row" key={i.id}>
                <span className={`bubble bubble--${i.state}`} aria-hidden />
                <div className="row__main">
                  <strong className={`status--${i.state}`}>{QUEUE_TEXT[i.state]}</strong>
                  <span>
                    {i.state === "rejected" || (i.state === "waiting" && i.attempts > 0)
                      ? i.error
                        ? `${i.filename}: ${i.error}`
                        : i.filename
                      : i.filename}
                  </span>
                  {i.state === "uploading" && (
                    <div
                      className="progress"
                      role="progressbar"
                      aria-label={`Uploading ${i.filename}`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round((i.progress ?? 0) * 100)}
                    >
                      <div style={{ width: `${Math.round((i.progress ?? 0) * 100)}%` }} />
                    </div>
                  )}
                </div>
                {i.state === "rejected" ? (
                  <button
                    type="button"
                    className="btn btn--quiet btn--small"
                    onClick={() => void queue.dismiss(i.id)}
                  >
                    Dismiss
                  </button>
                ) : i.state === "waiting" && i.attempts > 0 ? (
                  <button
                    type="button"
                    className="btn btn--quiet btn--small"
                    onClick={() => queue.retryNow()}
                  >
                    Retry
                  </button>
                ) : (
                  <span />
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      <h2 className="section-title">
        Recent scans <small>{event.code}</small>
      </h2>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      <ul className="rows" aria-label="Recent scans">
        {scans === null && <li className="empty">Loading…</li>}
        {scans?.length === 0 && (
          <li className="empty">
            No sheets scanned for this event yet. Start the camera or upload a photo.
          </li>
        )}
        {scans?.map((s) => (
          <li className="row" key={s.id} data-scan-id={s.id} data-status={s.status}>
            <span className={`bubble bubble--${s.status}`} aria-hidden />
            <div className="row__main">
              <strong>{s.team_number != null ? `Team ${s.team_number}` : "Team not read"}</strong>
              <span className={`status--${s.status}`}>
                {STATUS_TEXT[s.status]}
                {s.status === "needs_review" && s.flags.length > 0
                  ? `: ${s.flags.map((f) => f.replaceAll("_", " ")).join(", ")}`
                  : ""}
              </span>
            </div>
            <span className="row__score num">{s.mcq_score ?? ""}</span>
          </li>
        ))}
      </ul>
    </>
  );
}
