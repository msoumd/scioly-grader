import { useEffect, useState } from "react";
import { api, errorMessage, type EventOut, type Me } from "../api/client";

export function EventPicker({
  me,
  current,
  onPick,
  onLogout,
  onAuthLost,
}: {
  me: Me;
  current: string | null;
  onPick: (e: EventOut) => void;
  onLogout: () => void;
  onAuthLost: () => void;
}) {
  const [events, setEvents] = useState<EventOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .events()
      .then(setEvents)
      .catch((err) => {
        if (err?.status === 401) onAuthLost();
        else setError(errorMessage(err));
      });
  }, [onAuthLost]);

  return (
    <main className="page">
      <h1>Which event are you grading?</h1>
      <p className="hint">Logged in as {me.name}. This phone remembers your choice.</p>
      <h2 className="visually-hidden">Events</h2>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {events === null && !error && <p className="hint">Loading events…</p>}
      {events?.length === 0 && (
        <p className="alert alert--info">
          No events yet. A supervisor needs to import the event spreadsheet first.
        </p>
      )}
      {events && events.length > 0 && (
        <ul className="choice-list">
          {events.map((e) => (
            <li key={e.code}>
              <button
                type="button"
                className="choice"
                aria-pressed={e.code === current}
                onClick={() => onPick(e)}
              >
                <strong>{e.name}</strong>
                <span>
                  {e.tournament}, {e.question_count} questions
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p style={{ marginTop: 32 }}>
        <button type="button" className="btn btn--quiet btn--small" onClick={onLogout}>
          Log out
        </button>
      </p>
    </main>
  );
}
