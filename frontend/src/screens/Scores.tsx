import { useEffect, useMemo, useState } from "react";
import { api, errorMessage, type AuditOut, type EventOut, type ResultRow } from "../api/client";
import { useToast } from "../components/Toast";
import { keypadPress, parseFreeResponse, trim } from "../lib/freeResponse";
import { prefs } from "../lib/prefs";
import { go, href } from "../lib/route";
import { useResults } from "../lib/useResults";

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

export function ScoresList({ event, onAuthLost }: { event: EventOut; onAuthLost: () => void }) {
  const { data, error } = useResults(event.code, onAuthLost);
  const [search, setSearch] = useState("");
  const rows = useMemo(
    () =>
      [...(data?.rows ?? [])]
        .sort((a, b) => a.team_number - b.team_number)
        .filter((r) => !search || String(r.team_number).startsWith(search)),
    [data, search],
  );
  const left = data?.teams_without_free_response ?? 0;
  return (
    <>
      <h1 className="section-title" style={{ marginTop: 4 }}>
        Free response{" "}
        <small>{data ? `${left} to enter, out of ${trim(event.free_response_max)}` : ""}</small>
      </h1>
      <div className="field" style={{ marginBottom: 12 }}>
        <label htmlFor="team-search" className="visually-hidden">
          Find a team by number
        </label>
        <input
          id="team-search"
          inputMode="numeric"
          placeholder="Find team number"
          value={search}
          onChange={(e) => setSearch(e.target.value.replace(/\D/g, ""))}
        />
      </div>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      <ul className="rows" aria-label="Teams">
        {data === null && <li className="empty">Loading…</li>}
        {data && rows.length === 0 && (
          <li className="empty">
            {search
              ? `No team number starts with ${search}.`
              : "No teams yet. A supervisor imports the teams list in Setup."}
          </li>
        )}
        {rows.map((r) => (
          <li key={r.team_number}>
            <a className="row" href={href({ tab: "scores", team: r.team_number })}>
              <span
                className={`bubble ${r.free_response != null ? "bubble--confirmed" : "bubble--discarded"}`}
                aria-hidden
              />
              <div className="row__main">
                <strong>Team {r.team_number}</strong>
                <span>
                  {r.team_name}
                  {r.mcq == null ? ", no sheet yet" : ""}
                </span>
              </div>
              <span className="row__score num">
                {r.free_response != null ? trim(r.free_response) : "—"}
              </span>
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}

function nextWithoutScore(rows: ResultRow[], after: number): number | null {
  const sorted = [...rows].sort((a, b) => a.team_number - b.team_number);
  const pick = (r: ResultRow) => r.free_response == null && r.team_number !== after;
  return (
    (sorted.find((r) => r.team_number > after && pick(r)) ?? sorted.find(pick))?.team_number ?? null
  );
}

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "back"] as const;

export function ScoreEntry({
  event,
  team,
  onAuthLost,
}: {
  event: EventOut;
  team: number;
  onAuthLost: () => void;
}) {
  const { data, error: loadError } = useResults(event.code, onAuthLost, 15000);
  const row = data?.rows.find((r) => r.team_number === team);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<AuditOut[]>([]);
  const [fast, setFast] = useState(() => prefs.fastScores());
  const toast = useToast();

  useEffect(() => {
    let live = true;
    api
      .freeResponseHistory(event.code, team)
      .then((h) => live && setHistory(h))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [event.code, team, row?.free_response]);

  async function save(value: string) {
    setBusy(true);
    setError(null);
    try {
      await api.setFreeResponse(event.code, team, value);
      toast(`Team ${team}: free response ${value} saved`);
      setText("");
      setConfirming(null);
      const fresh = await api.results(event.code).catch(() => data);
      const next = fast && fresh ? nextWithoutScore(fresh.rows, team) : null;
      go(next != null ? { tab: "scores", team: next } : { tab: "scores" }, true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function submit() {
    const parsed = parseFreeResponse(text, event.free_response_max);
    if (!parsed.ok) return setError(parsed.error);
    if (row?.free_response != null) {
      if (trim(row.free_response) === parsed.value)
        return setError("That's already the saved value.");
      return setConfirming(parsed.value);
    }
    void save(parsed.value);
  }

  if (data && !row)
    return (
      <>
        <a className="back" href={href({ tab: "scores" })}>
          ‹ Teams
        </a>
        <p className="alert" role="alert">
          Team {team} isn't on the teams list.
        </p>
      </>
    );

  return (
    <>
      <a className="back" href={href({ tab: "scores" })}>
        ‹ Teams
      </a>
      <section className="panel entry" aria-label={`Team ${team} free response`}>
        <p className="entry__team num">Team {team}</p>
        <p className="entry__name">{row?.team_name ?? "…"}</p>
        {row?.free_response != null && (
          <p className="hint">
            Saved: <strong className="num">{trim(row.free_response)}</strong>
            {row.free_response_by ? ` by ${row.free_response_by}` : ""}
            {row.free_response_at ? ` at ${time(row.free_response_at)}` : ""}
          </p>
        )}
        <label className="entry__label" htmlFor="fr-value">
          Free-response total, out of {trim(event.free_response_max)}
        </label>
        <input
          id="fr-value"
          className="entry__value num"
          inputMode="none"
          autoComplete="off"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        {(error || loadError) && (
          <p className="warn-text" role="alert">
            {error ?? loadError}
          </p>
        )}
        <div className="keypad" role="group" aria-label="Number keypad">
          {KEYS.map((k) => (
            <button
              key={k}
              type="button"
              aria-label={k === "back" ? "Delete last digit" : k === "." ? "Decimal point" : k}
              onClick={() => {
                setText((t) => keypadPress(t, k));
                setError(null);
              }}
            >
              {k === "back" ? "⌫" : k}
            </button>
          ))}
        </div>
        {confirming ? (
          <div className="confirm-box" role="alertdialog" aria-label="Confirm change">
            <p>
              Change team {team}'s free response from{" "}
              <strong>{trim(row?.free_response ?? "")}</strong> to <strong>{confirming}</strong>?
            </p>
            <div className="actionbar__row">
              <button type="button" className="btn btn--quiet" onClick={() => setConfirming(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => void save(confirming)}
              >
                Change it
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            className="btn btn--block"
            disabled={busy || !row}
            onClick={submit}
            style={{ marginTop: 14 }}
          >
            {busy ? "Saving…" : "Save"}
          </button>
        )}
        <label className="check">
          <input
            type="checkbox"
            checked={fast}
            onChange={(e) => {
              setFast(e.target.checked);
              prefs.setFastScores(e.target.checked);
            }}
          />
          <span>After saving, go to the next team without a score</span>
        </label>
      </section>
      {history.length > 0 && (
        <details className="panel">
          <summary>History ({history.length})</summary>
          <ul className="history">
            {history.map((h) => (
              <li key={h.id}>
                {h.old_value == null
                  ? `${h.grader} entered ${trim(h.new_value ?? "")}`
                  : `${h.grader} changed it from ${trim(h.old_value)} to ${trim(h.new_value ?? "")}`}
                <time dateTime={h.created_at}>{time(h.created_at)}</time>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
