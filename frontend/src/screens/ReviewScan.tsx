import { useEffect, useMemo, useReducer, useState } from "react";
import {
  api,
  errorMessage,
  type AuditOut,
  type EventDetail,
  type EventOut,
  type Me,
  type QuestionRead,
  type ScanOut,
} from "../api/client";
import { ImageViewer } from "../components/ImageViewer";
import { useToast } from "../components/Toast";
import { eventDetail, preloadScan, takeScan, teamNames } from "../lib/data";
import { questionFlagText, scanFlagTexts } from "../lib/flags";
import {
  LETTERS,
  changedMarks,
  checkTeam,
  initReview,
  reviewReducer,
  teamChanged,
  typedTeam,
  type ReviewState,
} from "../lib/review";
import { go, href } from "../lib/route";
import { scoreSheet } from "../lib/scoring";

const TEAM_FLAG = /^team_(digit|alignment|low_contrast)/;

/** How sure the reader was, in words a grader understands. */
function readerSaw(q: QuestionRead): string {
  const seen = q.detected.length ? q.detected.join(", ") : "nothing";
  const why = q.flags.filter((f) => f !== "blank").map(questionFlagText);
  return `Reader saw ${seen}${why.length ? ` (${why.join(", ")})` : ""}`;
}

function when(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function historyText(a: AuditOut): string {
  const field = /^q\d+$/.test(a.field)
    ? `question ${a.field.slice(1)}`
    : a.field.replaceAll("_", " ");
  const v = (x: string | null) => (x === null || x === "" ? "blank" : x);
  return `${a.grader} changed ${field} from ${v(a.old_value)} to ${v(a.new_value)}`;
}

function Keypad({
  dispatch,
  digits,
}: {
  dispatch: (a: Parameters<typeof reviewReducer>[1]) => void;
  digits: number;
}) {
  return (
    <div className="keypad" role="group" aria-label="Team number keypad">
      {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => (
        <button
          key={d}
          type="button"
          onClick={() => dispatch({ type: "teamDigit", digit: d, maxDigits: digits })}
        >
          {d}
        </button>
      ))}
      <span />
      <button
        type="button"
        onClick={() => dispatch({ type: "teamDigit", digit: "0", maxDigits: digits })}
      >
        0
      </button>
      <button
        type="button"
        aria-label="Delete last digit"
        onClick={() => dispatch({ type: "teamBackspace" })}
      >
        ⌫
      </button>
    </div>
  );
}

function Letters({
  q,
  options,
  state,
  dispatch,
  detected,
}: {
  q: number;
  options: number;
  state: ReviewState;
  dispatch: (a: Parameters<typeof reviewReducer>[1]) => void;
  detected: string[];
}) {
  const marked = state.marks[q] ?? [];
  return (
    <div className="letters" role="group" aria-label={`Question ${q} answers`}>
      {LETTERS.slice(0, options)
        .split("")
        .map((l) => (
          <button
            key={l}
            type="button"
            className={`letter${detected.includes(l) ? " letter--seen" : ""}`}
            aria-pressed={marked.includes(l)}
            aria-label={`Question ${q} ${l}`}
            onClick={() => dispatch({ type: "toggle", q, letter: l, options })}
          >
            {l}
          </button>
        ))}
    </div>
  );
}

function Review({
  scan,
  event,
  detail,
  teams,
  me,
  onDone,
  onChanged,
}: {
  scan: ScanOut;
  event: EventOut;
  detail: EventDetail;
  teams: Map<number, string>;
  me: Me;
  onDone: (msg: string, nextId: number | null) => void;
  onChanged: (s: ScanOut) => void;
}) {
  const marks = useMemo(
    () => Object.fromEntries(scan.questions.map((q) => [q.q, q.marked])),
    [scan.questions],
  );
  const [state, dispatch] = useReducer(reviewReducer, undefined, () =>
    initReview(marks, scan.team_number ?? null),
  );
  const [acceptUnknown, setAcceptUnknown] = useState(false);
  const [editTeam, setEditTeam] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewer, setViewer] = useState<{ src: string; alt: string } | null>(null);
  const [history, setHistory] = useState<AuditOut[] | null>(null);

  const options = useMemo(() => new Map(detail.questions.map((q) => [q.q, q.options])), [detail]);
  const flaggedQs = useMemo(
    () =>
      new Set(
        scan.flags.filter((f) => /^q\d+:/.test(f)).map((f) => Number(f.slice(1).split(":")[0])),
      ),
    [scan.flags],
  );
  const flagged = scan.questions.filter((q) => flaggedQs.has(q.q));
  const others = scan.questions.filter((q) => !flaggedQs.has(q.q));
  const digits = event.team_number_digits;
  const team = checkTeam(state, teams);
  const teamProblem = scan.flags.some((f) => TEAM_FLAG.test(f)) || scan.team_number == null;
  const showPad = editTeam || teamProblem;
  const readable = scan.mcq_score != null;
  const duplicate = scan.flags.includes("duplicate_team") && !teamChanged(state);
  const pending = scan.status === "needs_review";
  const score = readable ? scoreSheet(state.marks, detail.questions) : null;
  const dirty = Object.keys(changedMarks(state)).length > 0 || teamChanged(state);
  const sceneFlags = scanFlagTexts(scan.flags);

  useEffect(() => {
    let live = true;
    api
      .history(scan.id)
      .then((h) => live && setHistory(h))
      .catch(() => live && setHistory([]));
    return () => {
      live = false;
    };
  }, [scan.id, scan.updated_at]);

  async function nextInQueue(): Promise<number | null> {
    try {
      const queue = await api.scans(event.code, "needs_review");
      return queue.find((s) => s.id !== scan.id)?.id ?? null;
    } catch {
      return null;
    }
  }

  async function save(): Promise<ScanOut> {
    const body: { marks?: Record<number, string[]>; team_number?: number | null } = {};
    const changed = changedMarks(state);
    if (Object.keys(changed).length) body.marks = changed;
    if (teamChanged(state)) body.team_number = typedTeam(state);
    return Object.keys(body).length ? api.correct(scan.id, body) : scan;
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await save();
      const done = await api.confirm(scan.id, team.state === "unknown" && acceptUnknown);
      onDone(`Team ${done.team_number} counted: ${done.mcq_score}`, await nextInQueue());
    } catch (err) {
      setError(errorMessage(err));
      api
        .scan(scan.id)
        .then(onChanged)
        .catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  async function discard(retake: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.discard(scan.id, retake ? "retake" : reason.trim() || undefined);
      if (retake) {
        onDone("Discarded. Take a new photo of this sheet.", null);
        go({ tab: "scan" });
      } else {
        onDone("Sheet discarded", await nextInQueue());
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function reopen() {
    setBusy(true);
    try {
      onChanged(await api.reopen(scan.id));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const canConfirm =
    pending &&
    readable &&
    !duplicate &&
    team.state !== "missing" &&
    (team.state !== "unknown" || acceptUnknown);

  // A team number that was read cleanly is one compact line under the flagged questions;
  // a problem with it (or "Change") shows the crop and keypad first.
  const teamFirst = teamProblem || team.state !== "ok" || duplicate || editTeam;
  const showCrop = teamFirst;
  const teamPanel = readable ? (
    <section
      className={`panel${teamProblem || team.state !== "ok" ? " panel--flagged" : ""}`}
      aria-label="Team number"
    >
      <h2>Team number</h2>
      {showCrop && scan.team_crop_url && (
        <img
          className="crop crop--team"
          src={scan.team_crop_url}
          alt="Team number as written and bubbled"
        />
      )}
      <div className="team-number num" aria-live="polite" aria-label="Team number typed">
        {state.teamText}
      </div>
      {team.state === "ok" && team.name && <p className="ok-text">{team.name}</p>}
      {team.state === "missing" && (
        <p className="warn-text">Type the team number from the sheet.</p>
      )}
      {team.state === "unknown" && (
        <>
          <p className="warn-text">Team {team.number} isn't on the teams list.</p>
          <label className="check">
            <input
              type="checkbox"
              checked={acceptUnknown}
              onChange={(e) => setAcceptUnknown(e.target.checked)}
            />
            <span>Count it for team {team.number} anyway (the sheet clearly says this number)</span>
          </label>
        </>
      )}
      {duplicate && (
        <p className="warn-text">
          Team {scan.team_number} already has a counted sheet.{" "}
          <a href={href({ tab: "duplicates" })}>Compare the sheets</a>
        </p>
      )}
      {pending &&
        (showPad ? (
          <Keypad dispatch={dispatch} digits={digits} />
        ) : (
          <button
            type="button"
            className="btn btn--quiet btn--small"
            onClick={() => setEditTeam(true)}
          >
            Change team number
          </button>
        ))}
    </section>
  ) : null;

  return (
    <>
      <a className="back" href={href({ tab: "review" })}>
        ‹ Review
      </a>
      <h1 className="section-title" style={{ marginTop: 0 }}>
        Sheet #{scan.id}
        <small>
          {scan.status === "needs_review"
            ? `scanned by ${scan.grader}`
            : scan.status.replace("_", " ")}
        </small>
      </h1>

      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {scan.status === "confirmed" && (
        <p className="alert alert--info">
          This sheet counts for team {scan.team_number} ({scan.mcq_score}).
          {me.role === "admin" ? " Re-open it to make a correction." : ""}
        </p>
      )}
      {scan.status === "discarded" && (
        <p className="alert alert--info">
          Discarded{scan.discard_reason ? `: ${scan.discard_reason}` : ""}. It never counts.
        </p>
      )}
      {pending && sceneFlags.length > 0 && (
        <p className="alert alert--info">Check: {sceneFlags.join("; ")}.</p>
      )}

      <div className="link-row">
        {scan.warped_url && (
          <button
            type="button"
            className="btn btn--quiet btn--small"
            onClick={() =>
              setViewer({ src: scan.warped_url!, alt: `Whole page, sheet #${scan.id}` })
            }
          >
            Show whole page
          </button>
        )}
        {scan.original_url && (
          <button
            type="button"
            className="btn btn--quiet btn--small"
            onClick={() =>
              setViewer({ src: scan.original_url!, alt: `Original photo, sheet #${scan.id}` })
            }
          >
            Show original photo
          </button>
        )}
      </div>
      {scan.photos_deleted && (
        <p className="hint" style={{ marginTop: -6 }}>
          This sheet's photos were deleted once it was{" "}
          {scan.status === "discarded" ? "discarded" : "counted"}. The answers and score are kept;
          check the paper sheet if you need to look again.
        </p>
      )}

      {!readable && pending && (
        <section className="panel panel--flagged">
          <h2>The page wasn't found in this photo</h2>
          <p className="hint">Retake the photo with all four black corner squares in view.</p>
        </section>
      )}

      {teamFirst && teamPanel}

      {flagged.map((q) => (
        <section key={q.q} className="panel panel--flagged" aria-label={`Question ${q.q}`}>
          <h2>Question {q.q}</h2>
          <p className="hint">{readerSaw(q)}</p>
          {q.crop_url && (
            <img className="crop" src={q.crop_url} alt={`Question ${q.q} on the sheet`} />
          )}
          {pending ? (
            <Letters
              q={q.q}
              options={options.get(q.q) ?? 4}
              state={state}
              dispatch={dispatch}
              detected={q.detected}
            />
          ) : (
            <p>
              Counted as <strong>{q.marked.join(", ") || "blank"}</strong>
            </p>
          )}
        </section>
      ))}

      {!teamFirst && teamPanel}

      {readable && others.length > 0 && (
        <details className="panel">
          <summary>Other answers ({others.length}) for a spot check</summary>
          <div className="spot">
            {others.map((q) => (
              <div key={q.q} style={{ display: "contents" }}>
                <span className="num">{q.q}</span>
                {pending ? (
                  <Letters
                    q={q.q}
                    options={options.get(q.q) ?? 4}
                    state={state}
                    dispatch={dispatch}
                    detected={[]}
                  />
                ) : (
                  <span>{q.marked.join(", ") || "blank"}</span>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      {history && history.length > 0 && (
        <details className="panel" open={!pending}>
          <summary>History ({history.length})</summary>
          <ul className="history">
            {history.map((h) => (
              <li key={h.id}>
                {historyText(h)}
                <time dateTime={h.created_at}>{when(h.created_at)}</time>
              </li>
            ))}
          </ul>
        </details>
      )}

      {discarding && (
        <section className="panel" aria-label="Discard sheet">
          <div className="field">
            <label htmlFor="reason">Why? (optional)</label>
            <input
              id="reason"
              value={reason}
              maxLength={200}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          <div className="actionbar__row">
            <button type="button" className="btn btn--quiet" onClick={() => setDiscarding(false)}>
              Keep it
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => void discard(false)}
            >
              Discard sheet
            </button>
          </div>
        </section>
      )}

      {pending && (
        <div className="actionbar">
          {score !== null && (
            <div className="actionbar__score">
              <span>Multiple choice{dirty ? " (with your changes)" : ""}</span>
              <strong className="num" aria-label="Score">
                {score}
              </strong>
            </div>
          )}
          {readable && (
            <button
              type="button"
              className="btn btn--block"
              disabled={!canConfirm || busy}
              onClick={() => void confirm()}
            >
              {busy
                ? "Saving…"
                : team.state === "missing"
                  ? "Type the team number"
                  : "Confirm and count"}
            </button>
          )}
          <div className="actionbar__row">
            <button
              type="button"
              className="btn btn--quiet"
              disabled={busy}
              onClick={() => void discard(true)}
            >
              Retake
            </button>
            <button
              type="button"
              className="btn btn--quiet"
              disabled={busy}
              onClick={() => setDiscarding(true)}
            >
              Discard
            </button>
          </div>
        </div>
      )}
      {scan.status === "confirmed" && me.role === "admin" && (
        <button
          type="button"
          className="btn btn--quiet btn--block"
          disabled={busy}
          onClick={() => void reopen()}
        >
          Re-open for correction
        </button>
      )}

      {viewer && <ImageViewer src={viewer.src} alt={viewer.alt} onClose={() => setViewer(null)} />}
    </>
  );
}

export function ReviewScan({
  scanId,
  event,
  me,
  onAuthLost,
}: {
  scanId: number;
  event: EventOut;
  me: Me;
  onAuthLost: () => void;
}) {
  const [data, setData] = useState<{
    scan: ScanOut;
    detail: EventDetail;
    teams: Map<number, string>;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    let live = true;
    Promise.all([takeScan(scanId), eventDetail(event.code), teamNames()])
      .then(([scan, detail, teams]) => live && setData({ scan, detail, teams }))
      .catch((err) => {
        if (!live) return;
        if (err?.status === 401) onAuthLost();
        else setError(errorMessage(err));
      });
    return () => {
      live = false;
    };
  }, [scanId, event.code, onAuthLost]);

  if (error)
    return (
      <>
        <a className="back" href={href({ tab: "review" })}>
          ‹ Review
        </a>
        <p className="alert" role="alert">
          {error}
        </p>
      </>
    );
  if (!data || data.scan.id !== scanId) return <p className="hint">Loading sheet…</p>;

  return (
    <Review
      key={`${data.scan.id}-${data.scan.status}`}
      scan={data.scan}
      event={event}
      detail={data.detail}
      teams={data.teams}
      me={me}
      onChanged={(scan) => setData({ ...data, scan })}
      onDone={(msg, nextId) => {
        toast(msg);
        if (nextId) {
          preloadScan(nextId);
          go({ tab: "review", scanId: nextId }, true);
        } else if (location.hash.startsWith("#/review")) {
          go({ tab: "review" }, true);
        }
      }}
    />
  );
}
