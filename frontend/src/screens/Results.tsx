import { Fragment, useMemo, useState } from "react";
import type { EventOut, Me, ResultRow } from "../api/client";
import { trim } from "../lib/freeResponse";
import { rankLabels } from "../lib/ranks";
import { href } from "../lib/route";
import { useResults } from "../lib/useResults";

type Filter = "all" | "no_scan" | "no_fr" | "review";

const FILTERS: Record<Filter, (r: ResultRow) => boolean> = {
  all: () => true,
  no_scan: (r) => r.mcq == null,
  no_fr: (r) => r.free_response == null,
  review: (r) => r.missing.includes("review"),
};

const when = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";

const pts = (v?: string | null) => (v == null ? "—" : trim(v));

export function Results({
  event,
  me,
  onAuthLost,
}: {
  event: EventOut;
  me: Me;
  onAuthLost: () => void;
}) {
  const { data, error } = useResults(event.code, onAuthLost);
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<number | null>(null);
  const labels = useMemo(() => rankLabels(data?.rows.map((r) => r.rank) ?? []), [data]);
  const shown = (data?.rows ?? [])
    .map((r, i) => ({ r, label: labels[i]! }))
    .filter(({ r }) => FILTERS[filter](r));
  const reviewTeams = data?.rows.filter(FILTERS.review).length ?? 0;

  const chip = (f: Filter, n: number, text: string) =>
    n > 0 && (
      <button
        type="button"
        className="chip chip--button"
        aria-pressed={filter === f}
        onClick={() => setFilter(filter === f ? "all" : f)}
      >
        {text}
      </button>
    );

  return (
    <>
      <div className="results-head">
        <h1 className="section-title" style={{ margin: "4px 0 0" }}>
          {event.name} results
        </h1>
        <p className="hint print-only">
          {event.tournament}. Printed {new Date().toLocaleString()}.
        </p>
      </div>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {data && (
        <div className="missing no-print" aria-label="What's missing">
          {data.teams_missing_something === 0 ? (
            <p className="ok-text" style={{ margin: 0 }}>
              Every team has both parts. Results are complete.
            </p>
          ) : (
            <>
              <p style={{ margin: "0 0 8px" }}>
                {data.teams_complete} of {data.rows.length} teams complete. Tap to show only:
              </p>
              <div className="chips">
                {chip(
                  "no_scan",
                  data.teams_without_scan,
                  `${data.teams_without_scan} with no scan`,
                )}
                {chip(
                  "no_fr",
                  data.teams_without_free_response,
                  `${data.teams_without_free_response} with no free response`,
                )}
                {chip("review", reviewTeams, `${reviewTeams} waiting for review`)}
              </div>
            </>
          )}
        </div>
      )}
      <div className="link-row no-print">
        <a
          className="btn btn--quiet btn--small"
          href={`/api/events/${encodeURIComponent(event.code)}/results.csv`}
          download
        >
          Download CSV
        </a>
        <button type="button" className="btn btn--quiet btn--small" onClick={() => window.print()}>
          Print
        </button>
        {me.role === "admin" && (
          <a className="btn btn--quiet btn--small" href={href({ tab: "setup" })}>
            Event setup
          </a>
        )}
      </div>
      <table className="results" aria-label="Results">
        <thead>
          <tr>
            <th scope="col">Rank</th>
            <th scope="col">Team</th>
            <th scope="col" className="r">
              MC
            </th>
            <th scope="col" className="r">
              FR
            </th>
            <th scope="col" className="r">
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {data === null && (
            <tr>
              <td colSpan={5} className="empty">
                Loading…
              </td>
            </tr>
          )}
          {data && shown.length === 0 && (
            <tr>
              <td colSpan={5} className="empty">
                {data.rows.length === 0
                  ? "No teams yet. Import the teams list in Event setup."
                  : "No teams match."}
              </td>
            </tr>
          )}
          {shown.map(({ r, label }) => (
            <Fragment key={r.team_number}>
              <tr
                data-team={r.team_number}
                className={open === r.team_number ? "is-open" : undefined}
                onClick={() => setOpen(open === r.team_number ? null : r.team_number)}
              >
                <td className="num rank">{label}</td>
                <td>
                  <button
                    type="button"
                    className="results__team"
                    aria-expanded={open === r.team_number}
                    aria-label={`Team ${r.team_number}, ${r.team_name}: details`}
                  >
                    <strong className="num">{r.team_number}</strong> {r.team_name}
                  </button>
                </td>
                <td className="num r">{pts(r.mcq)}</td>
                <td className="num r">{pts(r.free_response)}</td>
                <td className="num r total">{pts(r.total)}</td>
              </tr>
              {open === r.team_number && (
                <tr className="detail no-print">
                  <td colSpan={5}>
                    <dl>
                      <dt>Multiple choice</dt>
                      <dd>
                        {r.mcq != null ? (
                          <>
                            {trim(r.mcq)} from a sheet scanned by {r.mcq_by} at {when(r.mcq_at)}.{" "}
                            {r.scan_id && (
                              <a href={href({ tab: "review", scanId: r.scan_id })}>
                                Open the sheet and its history
                              </a>
                            )}
                          </>
                        ) : r.missing.includes("review") ? (
                          "A sheet is waiting for review."
                        ) : (
                          "No sheet scanned yet."
                        )}
                      </dd>
                      <dt>Free response</dt>
                      <dd>
                        {r.free_response != null
                          ? `${trim(r.free_response)} entered by ${r.free_response_by} at ${when(r.free_response_at)}. `
                          : "Not entered yet. "}
                        <a href={href({ tab: "scores", team: r.team_number })}>
                          {r.free_response != null ? "Change or see history" : "Enter it"}
                        </a>
                      </dd>
                    </dl>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </>
  );
}
