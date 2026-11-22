import { useEffect, useState, type ChangeEvent } from "react";
import {
  api,
  errorMessage,
  type EventImportOut,
  type EventOut,
  type Me,
  type TeamsImportOut,
} from "../api/client";
import { useToast } from "../components/Toast";
import { href } from "../lib/route";

type Pending<T> = { file: File; report: T } | null;

function FilePick({
  label,
  accept,
  onFile,
}: {
  label: string;
  accept: string;
  onFile: (f: File) => void;
}) {
  return (
    <label className="upload-label">
      <input
        type="file"
        accept={accept}
        aria-label={label}
        onChange={(e: ChangeEvent<HTMLInputElement>) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
      <span className="btn btn--quiet" aria-hidden>
        {label}
      </span>
    </label>
  );
}

export function Setup({ me, onEventsChanged }: { me: Me; onEventsChanged: () => void }) {
  const [events, setEvents] = useState<EventOut[]>([]);
  const [eventCheck, setEventCheck] = useState<Pending<EventImportOut>>(null);
  const [teamsCheck, setTeamsCheck] = useState<Pending<TeamsImportOut>>(null);
  const [rescore, setRescore] = useState<{ code: string; changed: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const loadEvents = () =>
    api
      .events()
      .then(setEvents)
      .catch((e) => setError(errorMessage(e)));
  useEffect(() => {
    const t = setTimeout(() => void loadEvents(), 0);
    return () => clearTimeout(t);
  }, []);

  if (me.role !== "admin")
    return (
      <main className="page">
        <h1>Event setup</h1>
        <p className="alert alert--info">Log in with the admin PIN to set up events and teams.</p>
        <a className="back" href={href({ tab: "scan" })}>
          ‹ Back
        </a>
      </main>
    );

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(errorMessage(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <a className="back" href={href({ tab: "scan" })}>
        ‹ Back to the app
      </a>
      <h1>Event setup</h1>
      <p className="hint">Each upload is checked first; nothing is saved until you press Import.</p>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      <h2>1. Event spreadsheet</h2>
      <FilePick
        label="Choose event spreadsheet (.xlsx)"
        accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        onFile={(file) =>
          void run(async () => setEventCheck({ file, report: await api.importEvent(file, true) }))
        }
      />
      {eventCheck && (
        <section className="panel" aria-label="Event import report" style={{ marginTop: 12 }}>
          <p className={eventCheck.report.report.ok ? "ok-text" : "warn-text"}>
            {eventCheck.report.report.ok
              ? `${eventCheck.file.name} looks good: ${eventCheck.report.report.question_count} questions.`
              : `${eventCheck.file.name} has problems. Fix them in the spreadsheet and choose it again.`}
          </p>
          <pre className="report">{eventCheck.report.report.text}</pre>
          {eventCheck.report.report.ok && (
            <button
              type="button"
              className="btn btn--block"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const r = await api.importEvent(eventCheck.file, false);
                  toast(
                    `Event ${r.event_code} ${r.action === "created" ? "imported" : r.action === "new_version" ? "imported as a new version" : "replaced"}`,
                  );
                  setEventCheck(null);
                  await loadEvents();
                  onEventsChanged();
                })
              }
            >
              Import event
            </button>
          )}
        </section>
      )}

      <h2>2. Teams list</h2>
      <p className="hint">A CSV file with the columns team_number,team_name.</p>
      <FilePick
        label="Choose teams list (.csv)"
        accept=".csv,text/csv"
        onFile={(file) =>
          void run(async () => setTeamsCheck({ file, report: await api.importTeams(file, true) }))
        }
      />
      {teamsCheck && (
        <section className="panel" aria-label="Teams import report" style={{ marginTop: 12 }}>
          <p className={teamsCheck.report.ok ? "ok-text" : "warn-text"}>
            {teamsCheck.report.ok
              ? `${teamsCheck.file.name}: ${teamsCheck.report.inserted} new teams, ${teamsCheck.report.updated} renamed.`
              : `${teamsCheck.file.name} has problems. Fix them and choose it again.`}
          </p>
          <pre className="report">{teamsCheck.report.text}</pre>
          {teamsCheck.report.ok && (
            <button
              type="button"
              className="btn btn--block"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const r = await api.importTeams(teamsCheck.file, false);
                  toast(`Teams saved: ${r.inserted} new, ${r.updated} renamed`);
                  setTeamsCheck(null);
                })
              }
            >
              Import teams
            </button>
          )}
        </section>
      )}

      <h2>3. Answer sheets and re-scoring</h2>
      {events.length === 0 && <p className="hint">No events yet. Import a spreadsheet above.</p>}
      <ul className="rows" aria-label="Events">
        {events.map((e) => (
          <li key={e.code} className="row" style={{ gridTemplateColumns: "1fr" }}>
            <div className="row__main">
              <strong>{e.name}</strong>
              <span>
                {e.code}, sheet version {e.sheet_version}, {e.question_count} questions,{" "}
                {e.scans_counted} sheets counted
              </span>
              <div className="link-row" style={{ margin: "8px 0 0" }}>
                <a
                  className="btn btn--quiet btn--small"
                  href={`/api/events/${encodeURIComponent(e.code)}/sheet.pdf`}
                  target="_blank"
                  rel="noopener"
                >
                  Answer sheet PDF
                </a>
                <button
                  type="button"
                  className="btn btn--quiet btn--small"
                  disabled={busy}
                  onClick={() =>
                    void run(async () =>
                      setRescore({
                        code: e.code,
                        changed: (await api.rescore(e.code, true)).changed,
                      }),
                    )
                  }
                >
                  Re-score
                </button>
              </div>
              {rescore?.code === e.code && (
                <div className="confirm-box" role="alertdialog" aria-label="Confirm re-score">
                  {rescore.changed === 0 ? (
                    <p>Every sheet already matches the current answer key. Nothing to change.</p>
                  ) : (
                    <p>
                      Re-scoring with the current answer key changes{" "}
                      <strong>{rescore.changed}</strong> sheet
                      {rescore.changed === 1 ? "" : "s"}. Each change is recorded in the history.
                    </p>
                  )}
                  <div className="actionbar__row">
                    <button
                      type="button"
                      className="btn btn--quiet"
                      onClick={() => setRescore(null)}
                    >
                      {rescore.changed === 0 ? "OK" : "Cancel"}
                    </button>
                    {rescore.changed > 0 && (
                      <button
                        type="button"
                        className="btn"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            const r = await api.rescore(e.code, false);
                            toast(
                              `Re-scored: ${r.changed} sheet${r.changed === 1 ? "" : "s"} changed`,
                            );
                            setRescore(null);
                          })
                        }
                      >
                        Re-score {rescore.changed}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
      <p className="hint" style={{ marginTop: 24 }}>
        Print answer sheets at 100% (actual size), not "fit to page".
      </p>
    </main>
  );
}
